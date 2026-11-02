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
        return m.group(1).strip()
    label = re.sub(r"\s+\d{1,2}:\d{2}\s*$", "", label).strip()
    return label


def parse_claims_from_ocr(ocr_results: List[Dict]) -> List[Dict[str, Any]]:
    """从 OCR 文本块解析领取明细。"""
    amounts: List[Tuple[float, List[int], str]] = []
    for item in ocr_results:
        label = (item.get("label") or "").strip()
        bbox = item.get("pixel_bbox") or item.get("bbox") or []
        if len(bbox) == 8:
            xs = bbox[0::2]
            ys = bbox[1::2]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
        if len(bbox) != 4:
            continue
        if "个红包" in label or ("共" in label and "元" in label):
            continue
        if "已领取" in label or "被抢光" in label:
            continue
        m = AMOUNT_RE.search(label)
        if m:
            amounts.append((float(m.group(1)), [int(v) for v in bbox], label))

    claims: List[Dict[str, Any]] = []
    for amount, amount_bbox, amount_label in amounts:
        ay = (amount_bbox[1] + amount_bbox[3]) / 2
        best_name = ""
        best_dist = 1e9
        for item in ocr_results:
            label = (item.get("label") or "").strip()
            bbox = item.get("pixel_bbox") or item.get("bbox") or []
            if len(bbox) == 8:
                xs = bbox[0::2]
                ys = bbox[1::2]
                bbox = [min(xs), min(ys), max(xs), max(ys)]
            if len(bbox) != 4 or not label:
                continue
            if AMOUNT_RE.search(label) and "月" not in label:
                if re.fullmatch(r"[\d.\s元]+", label):
                    continue
            if any(skip in label for skip in SKIP_LABELS):
                continue
            if "发出的红包" in label or ("共" in label and "元" in label):
                continue
            name = _extract_claim_name(label)
            if not name or _looks_like_chat_list_noise(name):
                continue
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
            logger.warning(f"金额 {amount_label} 未匹配到昵称")
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

    def parse_images(self, image_paths: List[str | Path]) -> List[Dict[str, Any]]:
        """
        多图识别。
        返回按截图顺序排列的领取列表（用于未抢包倒数第 N 兜底），
        每条含 order_index；同名保留首次出现位置，金额取较大者时仍保留原 index。
        """
        ordered: List[Dict[str, Any]] = []
        for p in image_paths:
            for c in self.parse_image(p):
                item = dict(c)
                item["order_index"] = len(ordered)
                ordered.append(item)
        logger.info(f"多图识别有序领取 {len(ordered)} 条")
        return ordered
