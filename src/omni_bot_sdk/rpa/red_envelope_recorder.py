"""
红包领取记录模块。
切换到群聊后点击红包卡片；仅当出现「查看领取详情」时进入详情并 OCR 领取明细。
关闭弹窗一律点击叉号，禁止 ESC（ESC 会关掉微信客户端）。
"""

import logging
import os
import re
import time
from typing import Dict, List, Optional, Tuple

import cv2
import httpx
import numpy as np
import pyautogui
from omni_bot_sdk.utils.helpers import get_center_point
from omni_bot_sdk.utils.mouse import human_like_mouse_move


class RedEnvelopeRecorder:
    """通过 OCR 记录群红包领取明细。"""

    CARD_KEYWORDS = ("微信红包", "恭喜发财", "大吉大利")
    # 红包领完后才出现
    DETAIL_LINK_KEYWORDS = ("查看领取详情", "领取详情")
    # 未领完弹层底部文案（其正下方是圆角关闭叉）
    LUCK_LINK_KEYWORDS = ("看看大家的手气", "大家的手气")
    OPEN_KEYWORDS = ("開", "开")
    AMOUNT_RE = re.compile(r"(\d+\.\d{2})\s*元")
    # 未领完时：关弹层 → 等 3 秒 → 再点红包
    RETRY_WAIT_SECONDS = 3.0
    MAX_UNFINISHED_RETRIES = 30
    SKIP_LABELS = {
        "发出的红包",
        "恭喜发财",
        "大吉大利",
        "微信红包",
        "手气最佳",
        "已领取",
        "看看大家的手气",
        "查看领取详情",
        "领取详情",
        "手慢了",
        "红包派完了",
        "拼",
    }

    def __init__(self, window_manager):
        self.logger = logging.getLogger(__name__)
        self.wm = window_manager
        self.ocr_processor = window_manager.ocr_processor
        self.image_processor = window_manager.image_processor

    @staticmethod
    def _is_valid_region(region: Optional[List[int]]) -> bool:
        if not region or len(region) != 4:
            return False
        try:
            left, top, width, height = [int(v) for v in region]
        except (TypeError, ValueError):
            return False
        return width > 10 and height > 10

    def _message_region(self) -> Optional[List[int]]:
        candidates = []
        cached = self.wm.get_message_region() if self.wm.current_window else None
        if cached:
            candidates.append(list(cached))

        msg_left = int(getattr(self.wm, "MSG_TOP_X", 0) or 0)
        msg_top = int(getattr(self.wm, "MSG_TOP_Y", 0) or 0) + 40
        msg_width = int(getattr(self.wm, "MSG_WIDTH", 0) or 0)
        win_w = int(getattr(self.wm.size_config, "width", 0) or 0)
        win_h = int(getattr(self.wm.size_config, "height", 0) or 0)
        if msg_width < 50 and win_w > 0:
            msg_width = max(int(win_w * 0.55), 200)
        msg_bottom = win_h - int(win_h * 0.18) if win_h > 0 else msg_top + 400
        msg_height = max(msg_bottom - msg_top, 100)
        if msg_left < 180:
            msg_left = 180
            msg_width = max(msg_width - 40, 200)
        candidates.append([msg_left, msg_top, msg_width, msg_height])

        win_region = self._window_region()
        if win_region:
            candidates.append(win_region)

        for region in candidates:
            if self._is_valid_region(region):
                region = [int(v) for v in region]
                self.logger.info(f"使用消息区域截图: {region}")
                return region

        self.logger.error(f"无法获取有效消息区域, candidates={candidates}")
        return None

    def _window_region(self) -> Optional[List[int]]:
        if self.wm.current_window:
            region = self.wm.current_window.get("region")
            if self._is_valid_region(region):
                return [int(v) for v in region]
        ox, oy = getattr(self.wm, "_screenshot_origin", (0, 0))
        w = int(getattr(self.wm.size_config, "width", 0) or 0)
        h = int(getattr(self.wm.size_config, "height", 0) or 0)
        region = [int(ox), int(oy), w, h]
        if self._is_valid_region(region):
            return region
        return None

    def _shot_ocr(self, region: List[int], save_path: str = "") -> List[Dict]:
        if not self._is_valid_region(region):
            self.logger.error(f"截图区域无效: {region}")
            return []
        screenshot = self.image_processor.take_screenshot(
            region=region,
            save_path=None,
        )
        if not screenshot:
            self.logger.error(f"截图失败, region={region}")
            return []
        if screenshot.size[0] < 2 or screenshot.size[1] < 2:
            self.logger.error(f"截图尺寸异常: {screenshot.size}, region={region}")
            return []
        if save_path:
            try:
                os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
                screenshot.save(save_path)
            except Exception as e:
                self.logger.warning(f"保存截图失败 {save_path}: {e}")
        results = self.ocr_processor.process_image(image=screenshot) or []
        self.logger.info(
            f"OCR 识别到 {len(results)} 个文本块: "
            f"{[r.get('label', '') for r in results[:20]]}"
        )
        ox, oy = region[0], region[1]
        for item in results:
            bbox = item.get("pixel_bbox") or []
            if len(bbox) == 4:
                item["pixel_bbox"] = [
                    bbox[0] + ox,
                    bbox[1] + oy,
                    bbox[2] + ox,
                    bbox[3] + oy,
                ]
        return results

    def _find_keyword_bbox(
        self, ocr_results: List[Dict], keywords: Tuple[str, ...]
    ) -> Optional[List[int]]:
        matches = []
        for item in ocr_results:
            label = (item.get("label") or "").strip()
            if not label:
                continue
            if any(k in label for k in keywords):
                bbox = item.get("pixel_bbox")
                if bbox and len(bbox) == 4:
                    matches.append(bbox)
        if not matches:
            return None
        matches.sort(key=lambda b: b[3], reverse=True)
        return matches[0]

    def _click_bbox(self, bbox: List[int], offset: Tuple[int, int] = (0, 0)) -> None:
        center = get_center_point(bbox)
        human_like_mouse_move(
            target_x=center[0] + offset[0],
            target_y=center[1] + offset[1],
        )
        pyautogui.click()
        time.sleep(getattr(self.wm, "action_delay", 0.3) or 0.3)

    def _click_xy(self, x: int, y: int) -> None:
        human_like_mouse_move(target_x=int(x), target_y=int(y))
        pyautogui.click()
        time.sleep(getattr(self.wm, "action_delay", 0.3) or 0.3)

    def _is_wechat_window_close_zone(
        self, bbox: List[int], region: List[int]
    ) -> bool:
        """微信客户端标题栏右上角关闭按钮区域，严禁点击。"""
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        rel_x = (cx - region[0]) / max(region[2], 1)
        rel_y = (cy - region[1]) / max(region[3], 1)
        return rel_y < 0.12 and rel_x > 0.82

    def _find_popup_close_mark(
        self, ocr_results: List[Dict], region: List[int]
    ) -> Optional[List[int]]:
        """
        仅接受弹层下方居中的圆角 X（排除微信窗口右上角关闭键）。
        """
        close_marks = ("×", "✕", "✖", "X", "x")
        candidates = []
        for item in ocr_results:
            label = (item.get("label") or "").strip()
            if label not in close_marks:
                continue
            bbox = item.get("pixel_bbox")
            if not bbox or len(bbox) != 4:
                continue
            if self._is_wechat_window_close_zone(bbox, region):
                self.logger.warning(f"忽略疑似微信窗口关闭按钮: {bbox}")
                continue
            cx = (bbox[0] + bbox[2]) / 2
            cy = (bbox[1] + bbox[3]) / 2
            rel_y = (cy - region[1]) / max(region[3], 1)
            rel_x = (cx - region[0]) / max(region[2], 1)
            # 弹层圆角 X 在窗口中下部、水平居中附近
            if rel_y < 0.45:
                continue
            if abs(rel_x - 0.5) > 0.25:
                continue
            candidates.append(bbox)
        if not candidates:
            return None
        # 取最靠下的（卡片下方叉）
        candidates.sort(key=lambda b: b[3], reverse=True)
        return candidates[0]

    def _click_below_text(
        self, bbox: List[int], offset_y: int, tip: str
    ) -> bool:
        cx = (bbox[0] + bbox[2]) // 2
        cy = bbox[3] + offset_y
        self.logger.info(f"{tip}: ({cx}, {cy})")
        self._click_xy(cx, cy)
        time.sleep(0.5)
        return True

    def _click_card_close_x(
        self, region: List[int], ocr_results: List[Dict]
    ) -> bool:
        """
        关闭未领完/开红包弹层：点「看看大家的手气」正下方的圆角 X。
        绝不可点微信窗口右上角关闭键。
        """
        # 1) 优先：文案正下方（最稳）
        luck = self._find_keyword_bbox(ocr_results, self.LUCK_LINK_KEYWORDS)
        if luck:
            return self._click_below_text(
                luck, 55, "按「看看大家的手气」下方点击圆角叉号"
            )

        detail_link = self._find_keyword_bbox(
            ocr_results, self.DETAIL_LINK_KEYWORDS
        )
        if detail_link:
            return self._click_below_text(
                detail_link, 55, "按「查看领取详情」下方点击圆角叉号"
            )

        open_btn = self._find_keyword_bbox(ocr_results, self.OPEN_KEYWORDS)
        if open_btn:
            # 開 下方还有「看看大家的手气」，叉号更靠下
            return self._click_below_text(
                open_btn, 130, "按「開」下方估算圆角叉号"
            )

        # 2) OCR 到的下方居中 X（已排除窗口右上角）
        mark = self._find_popup_close_mark(ocr_results, region)
        if mark:
            self.logger.info("OCR 命中弹层下方圆角叉号")
            self._click_bbox(mark)
            time.sleep(0.5)
            return True

        for kw, offset in (
            ("手慢了", 160),
            ("红包派完了", 160),
            ("恭喜发财", 250),
            ("发出的红包", 300),
        ):
            bbox = self._find_keyword_bbox(ocr_results, (kw,))
            if bbox:
                return self._click_below_text(
                    bbox, offset, f"按「{kw}」下方估算圆角叉号"
                )

        # 兜底：窗口水平居中、偏下（绝不用右上角）
        cx = region[0] + region[2] // 2
        cy = region[1] + int(region[3] * 0.72)
        self.logger.warning(f"兜底点击弹层下方叉号(居中偏下): ({cx}, {cy})")
        self._click_xy(cx, cy)
        time.sleep(0.5)
        return True

    def _detect_detail_red_header(
        self, region: List[int]
    ) -> Optional[Tuple[int, int, int, int, np.ndarray]]:
        """
        检测详情弹层红头。
        Returns:
            (local_x, local_y, w, h, frame) — 相对 region 截图的坐标；失败返回 None
        """
        if not self._is_valid_region(region):
            return None
        screenshot = self.image_processor.take_screenshot(
            region=region, save_path=None
        )
        if not screenshot:
            return None
        frame = np.array(screenshot)
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        mask1 = cv2.inRange(hsv, np.array([0, 70, 70]), np.array([18, 255, 255]))
        mask2 = cv2.inRange(
            hsv, np.array([160, 70, 70]), np.array([179, 255, 255])
        )
        mask = cv2.bitwise_or(mask1, mask2)
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return None

        img_h, img_w = mask.shape[:2]
        best = None
        best_area = 0
        for contour in contours:
            x, y, bw, bh = cv2.boundingRect(contour)
            area = bw * bh
            if y > img_h * 0.55:
                continue
            if area < 8000:
                continue
            # 详情红头通常在窗口中右部，排除左侧会话列表里的橙色气泡
            cx = x + bw / 2
            if cx < img_w * 0.35:
                continue
            if area > best_area:
                best_area = area
                best = (x, y, bw, bh)
        if not best:
            return None
        x, y, bw, bh = best
        self.logger.info(
            f"检测到详情红头 local=({x},{y},{bw},{bh}) area={best_area}"
        )
        return x, y, bw, bh, frame

    def _detail_claims_ocr_region(
        self, win_region: List[int]
    ) -> Optional[List[int]]:
        """
        仅截取详情弹层「白底领取列表」区域（图2）：
        - 左右：红头宽度（去掉左侧会话列表）
        - 上：红头下方（去掉红底标题区）
        """
        detected = self._detect_detail_red_header(win_region)
        if not detected:
            self.logger.warning("无法定位红头，详情 OCR 区域回退为消息区右半")
            # 兜底：窗口右 55% 偏中上，尽量避开左侧列表
            left = win_region[0] + int(win_region[2] * 0.42)
            top = win_region[1] + int(win_region[3] * 0.18)
            width = int(win_region[2] * 0.52)
            height = int(win_region[3] * 0.55)
            region = [left, top, width, height]
            if self._is_valid_region(region):
                return region
            return None

        x, y, bw, bh, frame = detected
        # 红头下方起算：再下移一点，跳过「发出的红包/祝福语/汇总行」
        local_left = max(0, x + 8)
        local_top = y + bh + 70
        local_w = max(80, bw - 16)
        local_h = max(120, int(bw * 1.35))
        max_h = frame.shape[0] - local_top - 20
        local_h = min(local_h, max_h)
        if local_h < 80:
            self.logger.warning("领取列表区域高度不足")
            return None

        region = [
            win_region[0] + local_left,
            win_region[1] + local_top,
            local_w,
            local_h,
        ]
        self.logger.info(f"详情领取列表 OCR 区域(图2): {region}")
        try:
            os.makedirs("runtime_images", exist_ok=True)
            debug = frame.copy()
            cv2.rectangle(debug, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
            cv2.rectangle(
                debug,
                (local_left, local_top),
                (local_left + local_w, local_top + local_h),
                (255, 255, 0),
                2,
            )
            cv2.imwrite(
                "runtime_images/red_envelope_claims_region.png",
                cv2.cvtColor(debug, cv2.COLOR_RGB2BGR),
            )
        except Exception:
            pass
        return region if self._is_valid_region(region) else None

    def _find_detail_red_header_close_xy(
        self, region: List[int]
    ) -> Optional[Tuple[int, int]]:
        """用红头右上角估算详情关闭黑 X 的屏幕坐标。"""
        detected = self._detect_detail_red_header(region)
        if not detected:
            self.logger.warning("未检测到详情红头区域")
            return None
        x, y, bw, bh, frame = detected
        local_ax = x + bw - 22
        local_ay = y + 18
        ax = region[0] + int(local_ax)
        ay = region[1] + int(local_ay)
        probe = [ax - 4, ay - 4, ax + 4, ay + 4]
        if self._is_wechat_window_close_zone(probe, region):
            ax = region[0] + int(x + bw - 40)
            ay = region[1] + int(y + 28)
            self.logger.warning("红头关闭点接近窗口关闭区，已内收")
        self.logger.info(f"红头关闭点=({ax}, {ay})")
        try:
            os.makedirs("runtime_images", exist_ok=True)
            debug = frame.copy()
            cv2.rectangle(debug, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
            cv2.circle(debug, (int(local_ax), int(local_ay)), 6, (255, 255, 0), -1)
            cv2.imwrite(
                "runtime_images/red_envelope_detail_close.png",
                cv2.cvtColor(debug, cv2.COLOR_RGB2BGR),
            )
        except Exception:
            pass
        return ax, ay

    def _click_detail_close_x(
        self, region: List[int], ocr_results: List[Dict]
    ) -> bool:
        """关闭领取详情页：点红底标题栏右上角黑色 X。"""
        xy = self._find_detail_red_header_close_xy(region)
        if xy:
            self.logger.info(f"按红头右上角点击关闭叉号: {xy}")
            self._click_xy(xy[0], xy[1])
            time.sleep(0.6)
            return True

        header = self._find_keyword_bbox(
            ocr_results, ("发出的红包", "恭喜发财")
        )
        if header:
            header_cx = (header[0] + header[2]) // 2
            ax = header_cx + 170
            ay = header[1] - 95
            max_x = region[0] + int(region[2] * 0.75)
            min_x = region[0] + int(region[2] * 0.52)
            ax = max(min_x, min(ax, max_x))
            min_y = region[1] + int(region[3] * 0.06)
            max_y = header[1] - 40
            ay = max(min_y, min(ay, max_y))
            probe = [ax - 4, ay - 4, ax + 4, ay + 4]
            if self._is_wechat_window_close_zone(probe, region):
                ax = header_cx + 140
                ay = header[1] - 70
            self.logger.info(f"按详情标题上方红区点击关闭叉号: ({ax}, {ay})")
            self._click_xy(ax, ay)
            time.sleep(0.6)
            return True

        self.logger.error("无法定位详情页红底关闭叉号")
        return False

    def _looks_like_chat_list_noise(self, label: str) -> bool:
        """左侧会话列表/系统提示等噪声，不能当领取人昵称。"""
        noise_keys = (
            "条]",
            "昨天",
            "今天",
            "星期",
            "领取了",
            "视频通话",
            "折叠",
            "搜索",
            "发送",
            "投保",
            "财务",
            "韩总",
            "邀请",
        )
        if any(k in label for k in noise_keys):
            return True
        if "：" in label or ":" in label:
            return True
        if re.search(r"\d{1,2}:\d{2}", label):
            return True
        return False

    def _extract_claim_name(self, label: str) -> str:
        """从 OCR 行提取昵称，例如「orion 10月26日9:05」→ orion。"""
        label = (label or "").strip()
        if not label:
            return ""
        m = re.match(r"^(.+?)\s*\d{1,2}月\d{1,2}日", label)
        if m:
            return m.group(1).strip()
        # 去掉尾部时间
        label = re.sub(r"\s+\d{1,2}:\d{2}\s*$", "", label).strip()
        return label

    def _parse_claims(self, ocr_results: List[Dict]) -> List[Dict]:
        """从详情领取列表 OCR 结果中解析昵称与金额。"""
        amounts: List[Tuple[float, List[int], str]] = []
        for item in ocr_results:
            label = (item.get("label") or "").strip()
            bbox = item.get("pixel_bbox") or []
            if len(bbox) != 4:
                continue
            if "个红包" in label or ("共" in label and "元" in label):
                continue
            if "已领取" in label or "被抢光" in label:
                continue
            m = self.AMOUNT_RE.search(label)
            if m:
                amounts.append((float(m.group(1)), bbox, label))

        claims = []
        for amount, amount_bbox, amount_label in amounts:
            ay = (amount_bbox[1] + amount_bbox[3]) / 2
            best_name = ""
            best_dist = 1e9
            for item in ocr_results:
                label = (item.get("label") or "").strip()
                bbox = item.get("pixel_bbox") or []
                if len(bbox) != 4 or not label:
                    continue
                if self.AMOUNT_RE.search(label) and "月" not in label:
                    # 「1.00元」跳过；「orion 10月..」留给姓名提取
                    if re.fullmatch(r"[\d.\s元]+", label):
                        continue
                if any(skip in label for skip in self.SKIP_LABELS):
                    continue
                if "发出的红包" in label or ("共" in label and "元" in label):
                    continue
                # 先去掉日期时间再判噪声，避免「orion 10月26日09:05」被误杀
                name = self._extract_claim_name(label)
                if not name or self._looks_like_chat_list_noise(name):
                    continue
                # 金额左侧、同一行
                if bbox[2] > amount_bbox[0] + 20:
                    continue
                cy = (bbox[1] + bbox[3]) / 2
                dist = abs(cy - ay)
                if dist < 50 and dist < best_dist:
                    best_dist = dist
                    best_name = name

            claims.append(
                {
                    "name": best_name,
                    "amount": amount,
                    "amount_text": f"{amount:.2f}元",
                }
            )
            if not best_name:
                self.logger.warning(f"金额 {amount_label} 未匹配到昵称")
        return claims

    @staticmethod
    def format_claims_message(claims: List[Dict], title: str = "") -> str:
        lines = ["【红包领取记录】"]
        if title:
            lines.append(f"祝福语：{title}")
        if not claims:
            lines.append("未能识别领取明细")
        else:
            for c in claims:
                name = c.get("name") or "未知"
                amt = c.get("amount_text") or f"{c.get('amount', 0):.2f}元"
                lines.append(f"{name}：{amt}")
        return "\n".join(lines)

    def _locate_red_packet_card(
        self, msg_region: List[int]
    ) -> Tuple[Optional[List[int]], Optional[List[int]]]:
        """定位聊天中的红包卡片，返回 (card_bbox, used_region)。"""
        ocr_results = self._shot_ocr(
            msg_region, save_path="runtime_images/red_envelope_chat.png"
        )
        card_bbox = self._find_keyword_bbox(ocr_results, self.CARD_KEYWORDS)
        used_region = msg_region
        if not card_bbox:
            win_region = self._window_region()
            if win_region and win_region != msg_region:
                self.logger.info("消息区未找到红包，尝试整窗 OCR")
                ocr_results = self._shot_ocr(
                    win_region,
                    save_path="runtime_images/red_envelope_chat_full.png",
                )
                card_bbox = self._find_keyword_bbox(
                    ocr_results, self.CARD_KEYWORDS
                )
                used_region = win_region
        return card_bbox, used_region

    def record(
        self,
        contact_name: str,
        title: str = "",
        callback_url: str = "",
        room_id: str = "",
        extra: Optional[Dict] = None,
    ) -> Dict:
        """
        切换会话 → 点红包卡：
        - 出现「查看领取详情」：进详情 OCR → 关详情 → 成功
        - 未领完（開 / 看看大家的手气）：点卡片下方圆角 X 关闭 → 等 3 秒 → 再点红包重试

        Returns:
            {"success": bool, "claims": list, "message": str, "finished": bool}
        """
        result = {
            "success": False,
            "claims": [],
            "message": "",
            "finished": False,
        }
        win_region = None
        try:
            self.logger.info(f"开始记录红包领取情况: {contact_name}, title={title}")
            if not self.wm.switch_session(contact_name):
                result["message"] = f"切换会话失败: {contact_name}"
                self.logger.error(result["message"])
                return result

            time.sleep(1.2)
            msg_region = self._message_region()
            if not msg_region:
                result["message"] = "无法定位消息区域"
                return result

            for attempt in range(1, self.MAX_UNFINISHED_RETRIES + 1):
                self.logger.info(
                    f"红包探测第 {attempt}/{self.MAX_UNFINISHED_RETRIES} 次"
                )
                card_bbox, _ = self._locate_red_packet_card(msg_region)
                if not card_bbox:
                    result["message"] = "未在聊天中找到红包卡片"
                    self.logger.warning(result["message"])
                    return result

                self._click_bbox(card_bbox, offset=(0, -10))
                time.sleep(1.2)

                win_region = self._window_region() or msg_region
                popup_ocr = self._shot_ocr(
                    win_region,
                    save_path="runtime_images/red_envelope_popup.png",
                )
                detail_link = self._find_keyword_bbox(
                    popup_ocr, self.DETAIL_LINK_KEYWORDS
                )

                if detail_link:
                    self.logger.info("检测到「查看领取详情」，进入详情页")
                    self._click_bbox(detail_link)
                    time.sleep(1.5)

                    # 只 OCR 图2 白底领取列表：去掉左侧会话列表 + 红头
                    claims_region = self._detail_claims_ocr_region(win_region)
                    ocr_region = claims_region or win_region
                    detail_ocr = self._shot_ocr(
                        ocr_region,
                        save_path="runtime_images/red_envelope_detail.png",
                    )
                    claims = self._parse_claims(detail_ocr)
                    self.logger.info(f"红包领取明细: {claims}")

                    payload = {
                        "event": "red_envelope_claims",
                        "room_name": contact_name,
                        "room_id": room_id,
                        "title": title,
                        "claims": claims,
                    }
                    if extra:
                        payload.update(extra)

                    if callback_url:
                        try:
                            resp = httpx.post(
                                callback_url, json=payload, timeout=10
                            )
                            self.logger.info(
                                f"红包领取明细已回调 {callback_url}, "
                                f"status={resp.status_code}"
                            )
                        except Exception as e:
                            self.logger.error(f"红包领取明细回调失败: {e}")

                    self._click_detail_close_x(win_region, detail_ocr)

                    result["success"] = True
                    result["finished"] = True
                    result["claims"] = claims
                    result["message"] = f"记录成功，共 {len(claims)} 条领取记录"
                    return result

                # 未领完：開 / 看看大家的手气 页面 → 点圆角 X → 等 3 秒再点
                self.logger.info(
                    "红包尚未领完（无「查看领取详情」），"
                    "点击「看看大家的手气」下方圆角叉号关闭，"
                    f"{self.RETRY_WAIT_SECONDS} 秒后重试"
                )
                self._click_card_close_x(win_region, popup_ocr)
                time.sleep(self.RETRY_WAIT_SECONDS)

            result["message"] = (
                f"红包在 {self.MAX_UNFINISHED_RETRIES} 次重试后仍未领完"
            )
            result["finished"] = False
            self.logger.warning(result["message"])
            return result
        except Exception as e:
            self.logger.error(f"记录红包领取失败: {e}", exc_info=True)
            try:
                region = win_region or self._window_region()
                if region:
                    ocr = self._shot_ocr(region)
                    # 只关红包弹层，绝不用窗口右上角逻辑
                    self._click_card_close_x(region, ocr)
            except Exception:
                pass
            result["message"] = str(e)
            return result
