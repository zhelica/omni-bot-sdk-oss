"""从红包领取详情截图识别昵称与金额（复用 red_envelope_recorder 解析逻辑）。"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)

AMOUNT_RE = re.compile(r"(\d+\.\d{2})\s*元?")
SKIP_LABELS = {
    "发出的红包",
    "恭喜发财",
    "大吉大利",
    "微信红包",
    "手气最佳",
    "已领取",
    "已存入零钱",
    "看看大家的手气",
    "查看领取详情",
    "领取详情",
    "手慢了",
    "红包派完了",
    "拼",
}


def _looks_like_chat_list_noise(label: str) -> bool:
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
        "邀请",
    )
    if any(k in label for k in noise_keys):
        return True
    if "：" in label or ":" in label:
        return True
    if re.search(r"\d{1,2}:\d{2}", label):
        return True
    return False


def _extract_claim_name(label: str) -> str:
    label = (label or "").strip()
    if not label:
        return ""
    m = re.match(r"^(.+?)\s*\d{1,2}月\d{1,2}日", label)
    if m:
        label = m.group(1).strip()
    else:
        # 日与时间粘连：11月04日20:24
        m = re.match(r"^(.+?)\s*\d{1,2}月\d{1,2}日\d{1,2}:\d{2}", label)
        if m:
            label = m.group(1).strip()
        else:
            label = re.sub(
                r"\s*\d{1,2}月\d{1,2}日\d{1,2}:\d{2}\s*$", "", label
            ).strip()
            # 时间可无空格粘连：167#tanwei14:49
            label = re.sub(r"\s*\d{1,2}:\d{2}\s*$", "", label).strip()
            # OCR 偶发把 14:49 读成 1449 / 6/1
            label = re.sub(r"\s+\d{3,4}\s*$", "", label).strip()
            label = re.sub(r"\s+\d+/\d+\s*$", "", label).strip()
    # 去掉尾部 @微信 / 微信，以及常见糊字（数信/收信/他信…）
    label = re.sub(
        r"(?:@微信|@信|微信|数信|收信|他信|特信|微情)\s*\d*$",
        "",
        label,
    ).strip()
    label = re.sub(r"\s+\d{1,3}$", "", label).strip()
    label = _ensure_remark_hash(label)
    return label


def _ensure_remark_hash(name: str) -> str:
    """
    统一成新备注格式 #编号#名称，便于只比对中间编号：
    - 已是 #0122#太阳 → 原样
    - 旧 0122#太阳 → #0122#太阳
    - 漏写 #：0122太阳 → #0122#太阳
    - OCR #0122太阳（缺中间 #）→ #0122#太阳
    """
    s = (name or "").strip()
    if not s:
        return s
    if re.match(r"^#\d{1,6}#", s):
        return s
    m = re.match(r"^(\d{1,6})#(.*)$", s)
    if m:
        return f"#{m.group(1)}#{m.group(2)}"
    m = re.match(r"^#(\d{1,6})(?!#)(.+)$", s)
    if m and re.match(r"^[\u4e00-\u9fffA-Za-z_、.]", m.group(2)):
        return f"#{m.group(1)}#{m.group(2)}"
    m = re.match(r"^(\d{2,6})(.+)$", s)
    if m and re.match(r"^[\u4e00-\u9fffA-Za-z_、.]", m.group(2)):
        return f"#{m.group(1)}#{m.group(2)}"
    return s


def _is_remark_style_name(name: str) -> bool:
    """备注格式：#001#xxx 或旧 001#xxx，优先于头像旁短词噪声。"""
    s = (name or "").strip()
    return bool(re.match(r"^#\d{1,6}#.", s) or re.match(r"^\d{1,6}#.", s))


def _name_dedupe_key(name: str) -> str:
    """同一领取人去重键：优先用 #编号# 中间编号。"""
    from omni_bot_sdk.game.settlement import _remark_match_key

    key = _remark_match_key(name)
    return key or re.sub(r"\s+", "", (name or "").strip()).lower()


def _bbox4(item: Dict) -> Optional[List[int]]:
    bbox = item.get("pixel_bbox") or item.get("bbox") or []
    if len(bbox) == 8:
        xs = bbox[0::2]
        ys = bbox[1::2]
        bbox = [min(xs), min(ys), max(xs), max(ys)]
    if len(bbox) != 4:
        return None
    return [int(v) for v in bbox]


def _find_grabbed_anchor_y(ocr_results: List[Dict]) -> Optional[float]:
    """定位「X个红包… / X秒被抢光」分隔线的 Y；领取列表从它下面开始。"""
    list_top_y = None
    for item in ocr_results:
        label = (item.get("label") or "").strip()
        bbox = _bbox4(item)
        if not bbox or not label:
            continue
        if (
            "被抢光" in label
            or "个红包" in label
            or ("已领取" in label and "元" in label)
            or ("共" in label and "元" in label and "红包" in label)
        ):
            y = (bbox[1] + bbox[3]) / 2
            list_top_y = y if list_top_y is None else max(list_top_y, y)
    return list_top_y


def parse_claims_from_ocr(ocr_results: List[Dict]) -> List[Dict[str, Any]]:
    """
    从 OCR 文本块解析领取明细。
    以「X个红包…」/「被抢光」分隔线为界：只收下方领取列表全部金额（有无昵称都保留），
    顶部本人大字金额不入列；兜底按自上而下第 N 个取金额，不因无备注跳过。
    """
    list_top_y = _find_grabbed_anchor_y(ocr_results)

    amounts: List[Tuple[float, List[int], str, str]] = []
    for item in ocr_results:
        label = (item.get("label") or "").strip()
        bbox = _bbox4(item)
        if not bbox:
            continue
        if "个红包" in label or ("共" in label and "元" in label):
            continue
        if "已领取" in label or "被抢光" in label:
            continue
        m = AMOUNT_RE.search(label)
        if not m:
            continue
        ay = (bbox[1] + bbox[3]) / 2
        # 有分隔线时，只保留其下方列表金额（排除顶部本人大字）
        if list_top_y is not None and ay <= list_top_y:
            continue
        # 昵称+金额粘在同一框：166#xxx0.07元 → 预拆昵称
        glued_name = ""
        prefix = label[: m.start()].strip()
        if prefix and not re.fullmatch(r"[\d.\s元]*", prefix):
            glued_name = _extract_claim_name(prefix)
            if glued_name and _looks_like_chat_list_noise(glued_name):
                glued_name = ""
        amounts.append((float(m.group(1)), bbox, label, glued_name))

    # 先按金额纵向收集候选昵称，再一对一贪心匹配：
    # 避免备注名因「优先备注 + 距离过宽」抢走邻行金额（如 167 抢走 0135 的 1.80）
    row_max_dist = 42.0
    pending: List[Dict[str, Any]] = []
    all_pairs: List[Tuple[float, int, int, str]] = []
    # pair = (score, amount_idx, remark_rank, name) ；score 越小越好
    for amount_idx, (amount, amount_bbox, amount_label, glued_name) in enumerate(
        amounts
    ):
        ay = (amount_bbox[1] + amount_bbox[3]) / 2
        gap = (ay - list_top_y) if list_top_y is not None else None
        pending.append(
            {
                "name": "",
                "amount": amount,
                "amount_text": f"{amount:.2f}元",
                "_ay": ay,
                "_gap_from_anchor": gap,
                "_amount_label": amount_label,
            }
        )
        if glued_name:
            # 粘连框内自带昵称，视为同排最优先
            all_pairs.append((0.0, amount_idx, 0, glued_name))
        for item in ocr_results:
            label = (item.get("label") or "").strip()
            bbox = _bbox4(item)
            if not bbox or not label:
                continue
            # 纯金额 / 昵称金额粘连框：不当独立昵称（粘连已走 glued_name）
            if AMOUNT_RE.search(label) and "月" not in label:
                continue
            if any(skip in label for skip in SKIP_LABELS):
                continue
            if (
                "发出的红包" in label
                or "个红包" in label
                or "被抢光" in label
                or ("共" in label and "元" in label)
            ):
                continue
            name = _extract_claim_name(label)
            if (
                not name
                or _looks_like_chat_list_noise(name)
                or "个红包" in name
                or "被抢光" in name
            ):
                continue
            if bbox[2] > amount_bbox[0] + 20:
                continue
            cy = (bbox[1] + bbox[3]) / 2
            dist = abs(cy - ay)
            if dist >= row_max_dist:
                continue
            left_penalty = 0.0
            if bbox[0] < 90 and len(name) <= 4 and not _is_remark_style_name(name):
                left_penalty = 40.0
            remark_rank = 0 if _is_remark_style_name(name) else 1
            # 同排优先看纵向距离；备注格式仅作轻量加分，避免跨行抢配
            score = dist + left_penalty + (0.0 if remark_rank == 0 else 8.0)
            all_pairs.append((score, amount_idx, remark_rank, name))

    all_pairs.sort(key=lambda x: (x[0], x[2]))
    used_amounts: set = set()
    used_names: set = set()
    for score, amount_idx, _rr, name in all_pairs:
        if amount_idx in used_amounts:
            continue
        nk = _name_dedupe_key(name)
        if not nk or nk in used_names:
            continue
        pending[amount_idx]["name"] = name
        used_amounts.add(amount_idx)
        used_names.add(nk)

    for row in pending:
        if not row.get("name"):
            logger.warning(
                f"金额 {row.get('_amount_label')} 未匹配到昵称，仍保留列表顺序供兜底"
            )
        row.pop("_amount_label", None)

    claims = pending
    # 按纵向位置自上而下，保证第 N 个与界面列表一致
    claims.sort(key=lambda c: c.get("_ay", 0))
    for c in claims:
        c.pop("_ay", None)
    return claims


def _normalize_ocr_items(raw: List[Dict]) -> List[Dict]:
    """兼容不同 OCR 返回字段。"""
    out = []
    for item in raw or []:
        label = item.get("label") or item.get("text") or item.get("txt") or ""
        bbox = item.get("pixel_bbox") or item.get("bbox") or item.get("box") or []
        conf = item.get("confidence", item.get("score", 1.0))
        out.append({"label": label, "pixel_bbox": bbox, "confidence": conf})
    return out


class ClaimImageOCR:
    """对本地红包详情截图做 OCR 并解析领取明细。"""

    def __init__(self, ocr_processor=None):
        self.ocr_processor = ocr_processor
        self._local_ocr = None

    def _ensure_local_ocr(self):
        if self.ocr_processor is not None:
            return
        if self._local_ocr is not None:
            return
        from omni_bot_sdk.rpa.ocr_processor import OCRProcessor

        self._local_ocr = OCRProcessor({})
        self._local_ocr.setup()

    def ocr_image(self, image_path: str | Path) -> List[Dict]:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"截图不存在: {path}")
        if self.ocr_processor is not None:
            raw = self.ocr_processor.process_image(image_path=str(path)) or []
            return _normalize_ocr_items(raw)

        self._ensure_local_ocr()
        raw = self._local_ocr.process_image(image_path=str(path)) or []
        return _normalize_ocr_items(raw)

    def parse_image(self, image_path: str | Path) -> List[Dict[str, Any]]:
        results = self.ocr_image(image_path)
        return parse_claims_from_ocr(results)

    @staticmethod
    def _claim_overlap_key(c: Dict[str, Any]) -> Tuple[str, float]:
        """重叠去重键：昵称（去空白小写）+ 金额。"""
        name = re.sub(r"\s+", "", str(c.get("name") or "")).strip().lower()
        try:
            amount = round(float(c.get("amount") or 0), 2)
        except (TypeError, ValueError):
            amount = 0.0
        return name, amount

    def parse_images(self, image_paths: List[str | Path]) -> List[Dict[str, Any]]:
        """
        多图识别并拼成自上而下总列表（order_index 连续编号）。

        顺序规则：
        1. 含「X秒被抢光 / X个红包」的图为第 1 张（不依赖上传先后）；
           该图内离「被抢光」最近的列表项 = 全局第 1 个。
        2. 其余图严格按上传/选择顺序接在后面（不要乱序选图）。
        3. 后一张若顶部与前一张末尾同一人（昵称+金额相同），自动跳过重叠行，
           建议第 2 张起截图带上上一张最后一人，便于对齐去重。
        """
        parsed: List[Tuple[int, Path, List[Dict[str, Any]], Optional[float]]] = []
        for i, p in enumerate(image_paths):
            path = Path(p)
            raw = self.ocr_image(path)
            claims = parse_claims_from_ocr(raw)
            anchor_y = _find_grabbed_anchor_y(raw)
            first_gap = None
            if claims and claims[0].get("_gap_from_anchor") is not None:
                first_gap = float(claims[0]["_gap_from_anchor"])
            elif anchor_y is not None:
                first_gap = 1e9
            parsed.append((i, path, claims, first_gap))

        with_anchor = [x for x in parsed if x[3] is not None]
        without_anchor = [x for x in parsed if x[3] is None]
        with_anchor.sort(key=lambda x: (x[3], x[0]))
        without_anchor.sort(key=lambda x: x[0])  # 上传顺序
        ordered_pages = with_anchor + without_anchor

        if with_anchor:
            logger.info(
                f"多图起始页: {ordered_pages[0][1].name} "
                f"(含「被抢光」, gap={ordered_pages[0][3]})"
            )
        else:
            logger.warning("多图均未识别到「被抢光」，按上传顺序拼接")

        ordered: List[Dict[str, Any]] = []
        for page_i, (_sel_i, path, claims, _gap) in enumerate(ordered_pages):
            start = 0
            if page_i > 0 and ordered and claims:
                # 后图开头与前图末尾重叠则跳过（支持「带上上一张最后一人」）
                prev_key = self._claim_overlap_key(ordered[-1])
                while start < len(claims):
                    cur_key = self._claim_overlap_key(claims[start])
                    # 无昵称时仅比金额，避免误伤；有昵称则昵称+金额
                    if cur_key[0]:
                        same = cur_key == prev_key
                    else:
                        same = abs(cur_key[1] - prev_key[1]) < 1e-9
                    if not same:
                        break
                    logger.info(
                        f"多图重叠去重: 跳过 {path.name} 第{start + 1}条 "
                        f"{claims[start].get('name') or '-'} "
                        f"{claims[start].get('amount')}"
                    )
                    start += 1
                    if start < len(claims):
                        # 只去与「当前末尾」连续重叠的开头；去完一条后末尾不变
                        pass

            for c in claims[start:]:
                item = dict(c)
                item.pop("_gap_from_anchor", None)
                item["order_index"] = len(ordered)
                ordered.append(item)
        logger.info(f"多图识别有序领取 {len(ordered)} 条（已按起始图+上传顺序拼接）")
        return ordered
