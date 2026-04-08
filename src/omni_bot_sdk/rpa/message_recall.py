"""
消息撤回模块。
提供微信消息撤回能力，通过OCR识别消息内容和右键菜单实现自动化撤回。
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

import pyautogui
from Levenshtein import ratio
from omni_bot_sdk.utils.helpers import get_bbox_center_exact
from omni_bot_sdk.utils.mouse import human_like_mouse_move


class MessageRecognizer:
    """
    消息识别器。
    通过OCR扫描微信聊天区域，识别消息内容和位置。
    """

    def __init__(self, window_manager):
        """
        初始化消息识别器。
        Args:
            window_manager: WindowManager实例
        """
        self.logger = logging.getLogger(__name__)
        self.wm = window_manager
        self.ocr_processor = window_manager.ocr_processor
        self.image_processor = window_manager.image_processor

    def _calculate_message_list_area(self) -> List[int]:
        """
        计算消息列表的实际区域。
        排除标题栏、输入区域、左侧联系人列表。
        Returns:
            [x, y, width, height] 消息区域
        """
        # 消息区域起始位置
        msg_top = self.wm.MSG_TOP_Y + 50  # 标题栏下方留点空白
        # 底部预留输入框和发送按钮区域（约18%高度）
        msg_bottom = self.wm.size_config.height - int(self.wm.size_config.height * 0.18)

        # 消息区域左右边界 - 使用 MSG_WIDTH 作为消息区域宽度
        msg_left = self.wm.MSG_TOP_X
        msg_width = max(self.wm.MSG_WIDTH, int(self.wm.size_config.width * 0.58))
        msg_right = msg_left + msg_width

        width = msg_right - msg_left
        height = msg_bottom - msg_top

        # 过滤掉左侧联系人列表的影响
        # 微信聊天界面左侧联系人列表宽度约 200-250 像素
        # 如果消息区域包含了这部分，需要排除
        min_msg_x = 200  # 消息区域最小X坐标，排除左侧联系人列表
        if msg_left < min_msg_x:
            msg_left = min_msg_x
            width = msg_right - msg_left

        self.logger.info(f"消息区域计算: left={msg_left}, top={msg_top}, width={width}, height={height}")

        return [msg_left, msg_top, width, height]

    def scan_messages(self, max_count: int = 30) -> List[Dict]:
        """
        扫描消息区域，返回消息列表。
        Args:
            max_count: 最大扫描消息数量
        Returns:
            消息列表，每条消息包含text、bbox、center、is_self、confidence
        """
        try:
            region = self._calculate_message_list_area()
            self.logger.info(f"扫描消息区域: {region}")

            screenshot = self.image_processor.take_screenshot(region=region)
            if not screenshot:
                self.logger.error("截取消息区域失败")
                return []

            # OCR识别
            ocr_results = self.ocr_processor.process_image(image=screenshot)
            if not ocr_results:
                self.logger.warning("OCR未识别到任何文本")
                return []

            self.logger.info(f"OCR识别到 {len(ocr_results)} 个文本块")

            # 转换为全局坐标并过滤
            messages = []
            msg_area_x = region[0]
            msg_area_y = region[1]
            msg_area_width = region[2]  # 从 region 中获取宽度

            for result in ocr_results:
                label = result.get("label", "").strip()
                if not label or len(label) < 1:
                    continue

                bbox = result.get("pixel_bbox", [])
                if len(bbox) != 4:
                    continue

                # 转换为全局坐标
                global_bbox = [
                    bbox[0] + msg_area_x,
                    bbox[1] + msg_area_y,
                    bbox[2] + msg_area_x,
                    bbox[3] + msg_area_y,
                ]

                # 过滤掉左侧联系人列表的内容
                # 微信界面左侧联系人列表宽度约 200 像素
                # 过滤掉 X 坐标小于 200 的内容
                if global_bbox[0] < 200:
                    continue

                # 过滤掉明显的非消息内容
                skip_keywords = ["微信", "搜索", "聊天", "文件", "视频", "图片",
                               "语音", "位置", "名片", "链接", "撤回", "相亲相", "rpa交流",
                               "terminal", "终端", "本地", "ERROR", "github", "docs"]
                if any(kw in label for kw in skip_keywords):
                    continue

                # 计算中心点
                center_x = (global_bbox[0] + global_bbox[2]) // 2
                center_y = (global_bbox[1] + global_bbox[3]) // 2

                # 判断是否为自己消息（靠右对齐）
                # 自己发送的消息通常在消息区域右侧
                msg_area_center_x = msg_area_x + msg_area_width // 2
                msg_area_right_boundary = msg_area_x + msg_area_width * 0.85
                is_self = global_bbox[0] > msg_area_center_x or global_bbox[2] > msg_area_right_boundary

                messages.append({
                    "text": label,
                    "bbox": global_bbox,
                    "center": (center_x, center_y),
                    "is_self": is_self,
                    "confidence": result.get("confidence", 0.5),
                    "raw_bbox": bbox,
                })

            # 按Y坐标排序（从上到下）
            messages.sort(key=lambda x: x["bbox"][1])
            self.logger.info(f"过滤后有效消息数: {len(messages)}")

            return messages[:max_count]

        except Exception as e:
            self.logger.error(f"扫描消息失败: {str(e)}")
            return []

    def find_message_by_text(
        self,
        target_text: str,
        similarity_threshold: float = 0.6,
        only_self: bool = True,
    ) -> Optional[Dict]:
        """
        根据文本查找消息。
        Args:
            target_text: 目标消息文本
            similarity_threshold: 相似度阈值
            only_self: 是否只查找自己的消息
        Returns:
            匹配的消息字典，未找到返回None
        """
        messages = self.scan_messages()

        if not messages:
            self.logger.warning("未扫描到任何消息")
            return None

        best_match = None
        best_score = 0
        # 记录所有满足阈值条件的匹配
        qualified_matches = []

        for msg in messages:
            # 如果只查找自己的消息，跳过他人的
            if only_self and not msg["is_self"]:
                continue

            # 计算相似度
            text = msg["text"]
            score = ratio(
                target_text,
                text,
                processor=lambda x: x.lower().replace(" ", "").replace("\n", ""),
                score_cutoff=0,
            )

            self.logger.info(f"消息: '{text[:30]}...' 相似度: {score:.2f}")

            if score >= similarity_threshold:
                qualified_matches.append((msg, score))

        # 从所有满足条件的匹配中选择：
        # 1. 优先选择相似度最高的
        # 2. 如果相似度相同，选择Y坐标最大的（最新的一条）
        if qualified_matches:
            # 按相似度降序，Y坐标降序排序
            qualified_matches.sort(key=lambda x: (x[1], x[0]["bbox"][1]), reverse=True)
            best_match, best_score = qualified_matches[0]
            self.logger.info(f"找到匹配消息，相似度: {best_score:.2f}, 文本: {best_match['text'][:50]}, 位置Y: {best_match['bbox'][1]:.0f}")

        return best_match

    def find_messages_by_keyword(
        self,
        keyword: str,
        similarity_threshold: float = 0.6,
        only_self: bool = True,
    ) -> List[Dict]:
        """
        根据关键词查找所有匹配的消息。
        支持精确包含和模糊匹配两种方式。
        Args:
            keyword: 关键词
            similarity_threshold: 相似度阈值（用于模糊匹配）
            only_self: 是否只查找自己的消息
        Returns:
            匹配的消息列表（按Y坐标排序，最新的在最后）
        """
        messages = self.scan_messages()
        matches = []

        keyword_lower = keyword.lower()

        for msg in messages:
            # 暂时跳过 is_self 检查，先找出所有匹配的消息
            # if only_self and not msg["is_self"]:
            #     continue

            text = msg["text"]
            text_lower = text.lower()

            # 方式1: 精确包含关键词
            if keyword_lower in text_lower:
                self.logger.info(f"[匹配] 精确包含: '{text[:30]}' (is_self={msg['is_self']})")
                if not only_self or msg["is_self"]:
                    matches.append(msg)
                else:
                    # 精确匹配但被 is_self 过滤，记录警告
                    self.logger.warning(f"[警告] 消息精确匹配但 is_self={msg['is_self']}: '{text[:30]}'")
                continue

            # 方式2: 关键词包含在识别文本中（处理OCR截断情况）
            if text_lower in keyword_lower:
                self.logger.info(f"[匹配] 反向包含: '{text[:30]}' (is_self={msg['is_self']})")
                if not only_self or msg["is_self"]:
                    matches.append(msg)
                else:
                    self.logger.warning(f"[警告] 消息反向匹配但 is_self={msg['is_self']}: '{text[:30]}'")
                continue

            # 方式3: 模糊匹配 - Levenshtein相似度
            score = ratio(
                keyword,
                text,
                processor=lambda x: x.lower().replace(" ", "").replace("\n", ""),
                score_cutoff=0,
            )

            if score >= similarity_threshold:
                self.logger.info(f"[匹配] 模糊匹配: '{text[:30]}' 相似度={score:.2f} (is_self={msg['is_self']})")
                if not only_self or msg["is_self"]:
                    msg["similarity"] = score
                    matches.append(msg)
                else:
                    self.logger.warning(f"[警告] 消息模糊匹配(相似度={score:.2f})但 is_self={msg['is_self']}: '{text[:30]}'")

        self.logger.info(f"关键词 '{keyword}' 匹配到 {len(matches)} 条消息（筛选前共{len([m for m in messages if keyword_lower in m['text'].lower() or m['text'].lower() in keyword_lower])} 条）")

        # 过滤出只自己的消息
        if only_self:
            self_msg = [m for m in matches if m["is_self"]]
            other_msg = [m for m in matches if not m["is_self"]]
            self.logger.info(f"  自己消息: {len(self_msg)} 条, 他人消息: {len(other_msg)} 条")
            matches = self_msg

        if matches:
            for i, m in enumerate(matches):
                self.logger.info(f"  候选[{i}]: Y={m['bbox'][1]:.0f}, x={m['bbox'][0]:.0f}, text='{m['text'][:30]}'")

        return matches


class ContextMenuHandler:
    """
    右键菜单处理器。
    处理右键点击和菜单识别操作。
    """

    def __init__(self, window_manager):
        """
        初始化右键菜单处理器。
        Args:
            window_manager: WindowManager实例
        """
        self.logger = logging.getLogger(__name__)
        self.wm = window_manager
        self.ocr_processor = window_manager.ocr_processor
        self.image_processor = window_manager.image_processor
        self.menu_region = None

    def right_click(self, x: int, y: int) -> bool:
        """
        在指定位置执行右键点击。
        Args:
            x: X坐标
            y: Y坐标
        Returns:
            是否成功
        """
        try:
            # 移动鼠标到目标位置
            human_like_mouse_move(target_x=x, target_y=y)
            time.sleep(0.2)

            # 右键点击
            pyautogui.click(x, y, button='right')
            self.logger.info(f"右键点击位置: ({x}, {y})")
            return True

        except Exception as e:
            self.logger.error(f"右键点击失败: {str(e)}")
            return False

    def _wait_for_menu(self, timeout: float = 2.0) -> bool:
        """
        等待菜单出现。
        Args:
            timeout: 超时时间（秒）
        Returns:
            是否等到菜单
        """
        start_time = time.time()
        check_interval = 0.1

        while time.time() - start_time < timeout:
            # 尝试检测菜单是否出现
            # 通过获取鼠标位置附近的颜色变化来判断
            try:
                # 获取屏幕某处是否有菜单特征
                # 这里简单等待固定时间
                time.sleep(check_interval)
            except Exception:
                pass

        # 等待足够时间让菜单渲染
        time.sleep(0.5)
        return True

    def _calculate_menu_region(self, click_x: int, click_y: int) -> List[int]:
        """
        计算菜单可能出现的区域。
        微信右键菜单通常出现在点击位置附近，大小和位置不固定。
        Args:
            click_x: 点击X坐标
            click_y: 点击Y坐标
        Returns:
            [x, y, width, height] 菜单区域
        """
        # 微信消息气泡右键菜单可能是多行的
        # 第一行包含：复制、放大阅读、翻译等
        # 第二行包含：多选、引用、撤回等
        # 菜单位置：通常在点击位置下方
        
        # 扩大区域以确保包含完整的菜单
        menu_width = 500  # 扩大宽度
        menu_height = 700  # 扩大高度，确保能截到多行菜单
        
        # 菜单从点击位置开始向下延伸
        # 点击位置在消息气泡中心，菜单位于气泡下方约20-50像素
        # 需要确保截图区域向下覆盖到第二行菜单
        menu_x = max(0, click_x - 250)  # 稍微向左扩展
        menu_y = click_y  # 从点击位置开始，向下截图
        # 确保截图区域能覆盖点击位置下方的所有菜单
        import pyautogui
        screen_w, screen_h = pyautogui.size()
        if menu_y + menu_height > screen_h:
            menu_height = screen_h - menu_y - 10  # 确保不超出屏幕
        
        self.logger.info(f"计算菜单位置: 点击=({click_x}, {click_y}), 菜单区域=[{menu_x}, {menu_y}, {menu_width}, {menu_height}]")

        return [menu_x, menu_y, menu_width, menu_height]

    def _capture_menu(self) -> Optional[Tuple]:
        """
        捕获右键菜单截图。
        Returns:
            (screenshot, region) 或 None
        """
        try:
            # 鼠标当前位置
            mouse_x, mouse_y = pyautogui.position()
            self.logger.info(f"当前鼠标位置: ({mouse_x}, {mouse_y})")

            # 计算菜单区域
            region = self._calculate_menu_region(mouse_x, mouse_y)
            self.menu_region = region

            # 截图
            screenshot = self.image_processor.take_screenshot(region=region)
            if screenshot:
                self.logger.info(f"菜单区域截图成功: {region}")
                return screenshot, region

            return None

        except Exception as e:
            self.logger.error(f"捕获菜单截图失败: {str(e)}")
            return None

    def find_recall_option(self) -> Optional[Tuple[int, int]]:
        """
        在右键菜单中查找"撤回"选项。
        Returns:
            (x, y) 撤回按钮的中心坐标，未找到返回None
        """
        try:
            # 捕获菜单
            result = self._capture_menu()
            if not result:
                self.logger.warning("无法捕获菜单截图")
                return None

            screenshot, region = result
            msg_area_x = region[0]
            msg_area_y = region[1]

            # 打印截图区域详细信息供调试
            self.logger.info(f"菜单截图区域: x={msg_area_x}, y={msg_area_y}, w={region[2]}, h={region[3]}")
            
            # OCR识别
            ocr_results = self.ocr_processor.process_image(image=screenshot)

            if not ocr_results:
                self.logger.warning("菜单OCR未识别到文本")
                return None

            self.logger.info(f"菜单OCR识别到 {len(ocr_results)} 个文本块")
            
            # 打印所有识别到的文本及其位置
            for r in ocr_results:
                label = r.get("label", "")
                bbox = r.get("pixel_bbox", [])
                # 计算全局坐标
                global_x = (bbox[0] + bbox[2]) // 2 + msg_area_x
                global_y = (bbox[1] + bbox[3]) // 2 + msg_area_y
                self.logger.info(f"  识别项: '{label}' 位置=({global_x}, {global_y})")

            # 查找"撤回"选项
            for result in ocr_results:
                label = result.get("label", "")
                bbox = result.get("pixel_bbox", [])

                # 匹配"撤回"关键词（支持截断匹配）
                if "撤回" in label or "撤销" in label:
                    # 计算中心点
                    center_x = (bbox[0] + bbox[2]) // 2 + msg_area_x
                    center_y = (bbox[1] + bbox[3]) // 2 + msg_area_y

                    self.logger.info(f"找到撤回选项: '{label}', 位置: ({center_x}, {center_y})")
                    return (center_x, center_y)

            # 如果没找到，列出所有识别到的文本供调试
            all_labels = [r.get("label", "") for r in ocr_results]
            self.logger.warning(f"未找到撤回选项，识别到的菜单项: {all_labels}")

            return None

        except Exception as e:
            self.logger.error(f"查找撤回选项失败: {str(e)}")
            return None

    def click_recall_option(self) -> bool:
        """
        点击撤回选项。
        Returns:
            是否成功
        """
        try:
            recall_pos = self.find_recall_option()

            if not recall_pos:
                self.logger.error("未找到撤回选项")
                return False

            x, y = recall_pos
            human_like_mouse_move(target_x=x, target_y=y)
            time.sleep(0.2)

            pyautogui.click(x, y)
            self.logger.info(f"点击撤回选项: ({x}, {y})")
            return True

        except Exception as e:
            self.logger.error(f"点击撤回选项失败: {str(e)}")
            return False

    def close_menu(self) -> bool:
        """
        关闭右键菜单（按ESC）。
        Returns:
            是否成功
        """
        try:
            pyautogui.press('escape')
            time.sleep(0.3)
            self.logger.info("已关闭右键菜单")
            return True
        except Exception as e:
            self.logger.error(f"关闭菜单失败: {str(e)}")
            return False


class MessageRecallController:
    """
    消息撤回控制器。
    整合消息识别和右键菜单操作，实现完整的消息撤回流程。
    """

    def __init__(self, window_manager):
        """
        初始化消息撤回控制器。
        Args:
            window_manager: WindowManager实例
        """
        self.logger = logging.getLogger(__name__)
        self.wm = window_manager
        self.message_recognizer = MessageRecognizer(window_manager)
        self.context_menu_handler = ContextMenuHandler(window_manager)

        # 配置参数
        self.config = {
            "max_retries": 3,  # 增加重试次数
            "right_click_duration": 0.1,
            "menu_wait_time": 1.0,  # 增加等待时间，确保菜单完全渲染
            "similarity_threshold": 0.6,
        }

    def recall_by_text(
        self,
        contact_name: str,
        message_text: str,
        similarity_threshold: float = 0.6,
        max_retries: int = 2,
    ) -> bool:
        """
        通过消息文本撤回消息。
        流程：
        1. 搜索并切换到目标联系人
        2. 在聊天区域查找匹配的消息
        3. 右键点击消息
        4. 在菜单中点击撤回

        Args:
            contact_name: 联系人名称
            message_text: 要撤回的消息内容
            similarity_threshold: 文本相似度阈值
            max_retries: 最大重试次数

        Returns:
            bool: 撤回是否成功
        """
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    self.logger.info(f"撤回重试 (第 {attempt + 1} 次)...")
                    time.sleep(1.0)

                # Step 1: 切换到目标联系人
                self.logger.info(f"切换到联系人: {contact_name}")
                if not self.wm.switch_session(contact_name):
                    self.logger.error(f"切换会话失败: {contact_name}")
                    continue

                time.sleep(0.5)

                # Step 2: 查找消息
                self.logger.info(f"查找消息: {message_text[:50]}...")
                # 精确文本匹配时放宽 is_self 限制，因为用户已明确指定要撤回的文本
                # 这样可以处理OCR误判的情况
                message = self.message_recognizer.find_message_by_text(
                    target_text=message_text,
                    similarity_threshold=similarity_threshold,
                    only_self=False,  # 放宽限制，让OCR有机会匹配到正确的消息
                )

                if not message:
                    # 尝试放宽条件查找
                    self.logger.info("精确匹配未找到，尝试模糊匹配...")
                    keyword_matches = self.message_recognizer.find_messages_by_keyword(
                        keyword=message_text[:10],  # 使用前10个字符作为关键词
                        similarity_threshold=0.5,
                        only_self=True,
                    )
                    if keyword_matches:
                        # 取最后一条（最新的消息，在屏幕最下方）
                        message = keyword_matches[-1]
                        self.logger.info(f"模糊匹配到 {len(keyword_matches)} 条，取最新的一条 (Y={message['bbox'][1]:.0f})")

                if not message:
                    self.logger.error(f"未找到消息: {message_text[:30]}...")
                    continue

                msg_center = message["center"]
                self.logger.info(f"找到消息，位置: {msg_center}, 内容: {message['text'][:30]}...")

                # Step 3: 右键点击消息
                self.logger.info(f"右键点击消息位置: {msg_center}")
                if not self.context_menu_handler.right_click(msg_center[0], msg_center[1]):
                    self.logger.error("右键点击失败")
                    continue

                # Step 4: 等待菜单出现
                time.sleep(self.config["menu_wait_time"])

                # Step 5: 查找并点击撤回
                if self.context_menu_handler.click_recall_option():
                    self.logger.info("撤回操作成功")
                    # 撤回成功后不按ESC，因为撤回按钮点击后菜单会自动消失
                    # 按ESC可能导致微信窗口被隐藏或最小化
                    time.sleep(0.5)
                    return True
                else:
                    self.logger.error("点击撤回选项失败")
                    self.context_menu_handler.close_menu()
                    continue

            except Exception as e:
                self.logger.error(f"撤回过程出错: {str(e)}")
                self.context_menu_handler.close_menu()
                continue

        self.logger.error(f"消息撤回失败，已重试 {max_retries} 次")
        return False

    def recall_latest_message(
        self,
        contact_name: str,
        max_retries: int = 2,
    ) -> bool:
        """
        撤回指定联系人的最新一条消息。

        Args:
            contact_name: 联系人名称
            max_retries: 最大重试次数

        Returns:
            bool: 撤回是否成功
        """
        try:
            # 切换到目标联系人
            self.logger.info(f"切换到联系人: {contact_name}")
            if not self.wm.switch_session(contact_name):
                self.logger.error(f"切换会话失败: {contact_name}")
                return False

            time.sleep(0.5)

            # 扫描消息
            messages = self.message_recognizer.scan_messages(max_count=5)

            # 过滤出自己的消息
            self_messages = [m for m in messages if m["is_self"]]

            if not self_messages:
                self.logger.error("未找到自己的消息")
                return False

            # 获取最新的一条（排序后最后一条）
            latest_message = self_messages[-1]
            msg_center = latest_message["center"]

            self.logger.info(f"找到最新消息，位置: {msg_center}, 内容: {latest_message['text'][:30]}...")

            # 右键点击
            if not self.context_menu_handler.right_click(msg_center[0], msg_center[1]):
                return False

            time.sleep(self.config["menu_wait_time"])

            # 点击撤回
            if self.context_menu_handler.click_recall_option():
                self.logger.info("最新消息撤回成功")
                # 撤回成功后不按ESC，因为撤回按钮点击后菜单会自动消失
                time.sleep(0.5)
                return True
            else:
                self.context_menu_handler.close_menu()
                return False

        except Exception as e:
            self.logger.error(f"撤回最新消息失败: {str(e)}")
            self.context_menu_handler.close_menu()
            return False

    def recall_by_keyword(
        self,
        contact_name: str,
        keyword: str,
        max_retries: int = 2,
    ) -> bool:
        """
        通过关键词撤回消息（撤回匹配的第一条消息）。

        Args:
            contact_name: 联系人名称
            keyword: 关键词
            max_retries: 最大重试次数

        Returns:
            bool: 撤回是否成功
        """
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    self.logger.info(f"撤回重试 (第 {attempt + 1} 次)...")
                    time.sleep(1.0)

                # 切换到目标联系人
                self.logger.info(f"切换到联系人: {contact_name}")
                if not self.wm.switch_session(contact_name):
                    continue

                time.sleep(0.5)

                # 通过关键词查找消息
                # 使用 only_self=True 只撤回自己的消息
                matches = self.message_recognizer.find_messages_by_keyword(
                    keyword=keyword,
                    similarity_threshold=0.5,
                    only_self=True,  # 关键词撤回需要严格验证是本人的消息
                )

                if not matches:
                    self.logger.error(f"未找到包含关键词 '{keyword}' 的消息")
                    continue

                # 使用第一条匹配的消息
                message = matches[0]
                msg_center = message["center"]

                self.logger.info(f"找到消息，位置: {msg_center}, 内容: {message['text'][:30]}...")

                # 右键点击
                if not self.context_menu_handler.right_click(msg_center[0], msg_center[1]):
                    continue

                time.sleep(self.config["menu_wait_time"])

                # 点击撤回
                if self.context_menu_handler.click_recall_option():
                    self.logger.info("撤回成功")
                    # 撤回成功后不按ESC，因为撤回按钮点击后菜单会自动消失
                    time.sleep(0.5)
                    return True
                else:
                    self.context_menu_handler.close_menu()
                    continue

            except Exception as e:
                self.logger.error(f"撤回过程出错: {str(e)}")
                self.context_menu_handler.close_menu()
                continue

        return False

    def recall_multiple_by_keyword(
        self,
        contact_name: str,
        keyword: str,
        max_count: int = 10,
        interval: float = 1.0,
    ) -> int:
        """
        撤回所有匹配关键词的消息。

        Args:
            contact_name: 联系人名称
            keyword: 关键词
            max_count: 最大撤回数量
            interval: 每次撤回间隔（秒）

        Returns:
            int: 成功撤回的数量
        """
        success_count = 0

        for i in range(max_count):
            self.logger.info(f"尝试撤回第 {i + 1} 条匹配消息...")

            # 每次都重新扫描，因为撤回后消息会消失
            matches = self.message_recognizer.find_messages_by_keyword(
                keyword=keyword,
                similarity_threshold=0.5,
                only_self=True,
            )

            if not matches:
                self.logger.info("没有更多匹配的消息")
                break

            # 取第一条
            message = matches[0]
            msg_center = message["center"]

            # 右键点击
            if not self.context_menu_handler.right_click(msg_center[0], msg_center[1]):
                time.sleep(0.5)
                continue

            time.sleep(self.config["menu_wait_time"])

            # 点击撤回
            if self.context_menu_handler.click_recall_option():
                success_count += 1
                self.logger.info(f"已撤回 {success_count} 条消息")
                # 撤回成功后不按ESC，因为撤回按钮点击后菜单会自动消失
                time.sleep(interval)
            else:
                self.context_menu_handler.close_menu()
                time.sleep(0.5)

        self.logger.info(f"批量撤回完成，成功 {success_count} 条")
        return success_count
