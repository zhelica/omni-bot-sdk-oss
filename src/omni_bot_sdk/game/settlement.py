"""有庄/无庄结算引擎与报表生成。"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from omni_bot_sdk.game.store import GameStore

logger = logging.getLogger(__name__)


def amount_to_point(amount: float) -> int:
    """
    红包金额数字位相加取个位。
    例：2.18 → 2+1+8=11 → 1；2.08 → 2+0+8=10 → 0
    """
    text = f"{float(amount):.2f}"
    digits = [int(ch) for ch in text if ch.isdigit()]
    return sum(digits) % 10


# 写死数字强度：0>9>8>7>6>5>4>3>2>1（不再可配置）
DIGIT_STRENGTH_ORDER = "0987654321"


def digit_strength(ch: str) -> int:
    """单个数字强度，越大越强。"""
    try:
        return len(DIGIT_STRENGTH_ORDER) - 1 - DIGIT_STRENGTH_ORDER.index(str(ch))
    except ValueError:
        return -1


def normalize_combo(combo: str) -> str:
    """
    先按数字强度从强到弱重排，再用于对比。
    例：045 → 054；054 → 054；036 → 063
    """
    digits = [ch for ch in (combo or "") if ch.isdigit()]
    return "".join(sorted(digits, key=digit_strength, reverse=True))


def amount_to_combo(amount: float) -> str:
    """
    红包金额 → 组合：取数字后按 0>9>…>1 重排。
    例：0.45→045→054；0.36→036→063；2.18→218→281
    """
    text = f"{float(amount):.2f}"
    raw = "".join(ch for ch in text if ch.isdigit())
    return normalize_combo(raw)


def combo_sorted_by_strength(combo: str) -> Tuple[str, ...]:
    """兼容：返回重排后的数字元组。"""
    return tuple(normalize_combo(combo))


def combo_compare_key(combo: str) -> Tuple[int, ...]:
    """
    组合已（或先）重排后，从左到右比强度。
    例：063 与 054 → 先比 0=0，再比 6>5 → 063 胜。
    """
    sorted_combo = normalize_combo(combo)
    if not sorted_combo:
        return (-1,)
    return tuple(digit_strength(ch) for ch in sorted_combo)


def combos_equal(a: str, b: str) -> bool:
    """重排后字符串相同则相等（045==054）。"""
    return normalize_combo(a) == normalize_combo(b)


def combo_weight_key(combo: str, order: str = "") -> Tuple[int, ...]:
    """兼容旧名；order 已忽略。"""
    _ = order
    return combo_compare_key(combo)


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip()).lower()


def _remark_match_key(name: str) -> str:
    """
    备注匹配键（只取编号，隔离后面 @微信 / @企业名）：
    - 新格式 #167#tanwei@微信 → 两 # 之间的 167
    - 旧格式 167#tanwei → 第一个 # 前的 167（兼容）
    - 无可用编号 → 全名
    """
    raw = (name or "").strip()
    if not raw:
        return ""
    # 新格式：#编号#名称…
    m = re.search(r"#(\d{1,6})#", raw)
    if m:
        return _norm_name(m.group(1))
    # 旧格式：编号#名称…
    head = raw.split("#", 1)[0].strip() if "#" in raw else ""
    if re.fullmatch(r"\d{1,6}", head or ""):
        return _norm_name(head)
    # OCR 偶发 #167tanwei（缺中间 #）
    m = re.match(r"^#(\d{1,6})", raw)
    if m:
        return _norm_name(m.group(1))
    return _norm_name(raw)


def match_claim_name(
    nickname: str, claims: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    将下注备注匹配到 OCR 领取记录。
    优先用 #编号# 中间编号精确匹配；再尝试全名精确/包含匹配。
    """
    target_key = _remark_match_key(nickname)
    target_full = _norm_name(nickname)
    if not target_key and not target_full:
        return None
    key_exact: List[Dict[str, Any]] = []
    full_exact: List[Dict[str, Any]] = []
    fuzzy: List[Dict[str, Any]] = []
    for c in claims:
        claim_name = c.get("name") or ""
        ck = _remark_match_key(claim_name)
        cn = _norm_name(claim_name)
        if not ck and not cn:
            continue
        # 1) 编号键：#167#a@微信 ↔ #167#b@企业名 / 旧 167#xxx
        if target_key and ck and target_key == ck:
            key_exact.append(c)
        # 2) 全名精确
        elif target_full and cn and target_full == cn:
            full_exact.append(c)
        # 3) 全名包含（兼容旧数据）
        elif target_full and cn and (target_full in cn or cn in target_full):
            fuzzy.append(c)
    if key_exact:
        return key_exact[0]
    if full_exact:
        return full_exact[0]
    if fuzzy:
        return fuzzy[0]
    return None


def match_claim_names(
    names: List[str], claims: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """按候选名优先级依次匹配红包领取。"""
    seen = set()
    for name in names:
        key = _remark_match_key(name) or _norm_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        matched = match_claim_name(name, claims)
        if matched:
            return matched
    return None


def resolve_packet_claim(
    nickname: str,
    ordered_claims: List[Dict[str, Any]],
    is_banker: bool = False,
    aliases: Optional[List[str]] = None,
) -> Tuple[Optional[Dict[str, Any]], str, List[str]]:
    """
    按玩法解析点数来源：
    - 有领取记录：按备注 #编号# 中间编号匹配（完整备注仅用于展示）
    - 无领取记录兜底（从下方领取列表自上而下，不含顶部本人金额）：
      · 无庄：取第 2 个
      · 有庄：取第 3 个
      · 不足则降级取最后一个并告警
    aliases 保留兼容。
    """
    _ = aliases  # 红包只比对备注编号，忽略别名兜底
    warnings: List[str] = []
    n = len(ordered_claims or [])
    matched = match_claim_name(nickname, ordered_claims)
    if matched:
        return matched, "", warnings

    # 无庄取第2个(index=1)；有庄取第3个(index=2)
    need_nth = 3 if is_banker else 2
    need_idx = need_nth - 1
    note = f"未抢包取自上而下第{need_nth}个"
    if n > need_idx:
        return ordered_claims[need_idx], note, warnings
    if n >= 1:
        warnings.append(
            f"未抢包需自上而下第{need_nth}个，但仅{n}个红包，降级取最后一个"
        )
        return ordered_claims[-1], "未抢包降级取最后一个", warnings
    warnings.append(f"玩家[{nickname}]未抢包且无红包记录")
    return None, "无红包记录", warnings


class SettlementEngine:
    def __init__(self, store: GameStore, report_dir: str | Path = "game_records"):
        self.store = store
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.last_warnings: List[str] = []

    def build_player_rows(
        self,
        bets: List[Dict[str, Any]],
        claims: List[Dict[str, Any]],
        room_name: str,
        banker_name: str = "",
        include_invalid: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        构建结算行。
        - 有效下注参与赔付
        - 无效/失败下注可入表（delta=0，备注失败原因），不赔付
        """
        rows = []
        self.last_warnings = []
        banker_key = _norm_name(banker_name)

        def _skip_non_bet_invalid(bet_row: Dict[str, Any]) -> bool:
            """
            取消/不压/无效撤注、非数字文字等：不进入结算结果表。
            余额不足、低于最低等「发过数字但校验失败」仍可按 include_invalid 展示。
            """
            reason = str(bet_row.get("invalid_reason") or "")
            content = str(bet_row.get("content") or "").strip()
            skip_keys = (
                "玩家主动无效",
                "非数字",
                "非数字忽略",
                "非数字无效",
            )
            if any(k in reason for k in skip_keys):
                return True
            # 内容本身是撤注词且非有效数字下注
            if content in {"无效", "取消", "不压"} and not bool(bet_row.get("is_valid", 1)):
                return True
            return False

        for bet in bets:
            is_valid = bool(bet.get("is_valid", 1))
            if not is_valid and _skip_non_bet_invalid(bet):
                continue
            if not is_valid and not include_invalid:
                continue
            # bet.nickname 现为比对名（备注优先）；账户可能是 GUI 另一昵称
            claim_nick = bet.get("nickname") or ""
            wxid = bet.get("wxid") or ""
            player = self.store.get_player(claim_nick, room_name) if claim_nick else None
            if not player and wxid:
                for p in self.store.list_players(room_name):
                    if str(p.get("wxid") or "").strip() == str(wxid).strip():
                        player = p
                        break
            # 备注 #001#洋洋 与账户 #001#chat 用编号键关联
            if not player and claim_nick:
                claim_key = _remark_match_key(claim_nick)
                if claim_key:
                    for p in self.store.list_players(room_name):
                        if _remark_match_key(p.get("nickname") or "") == claim_key:
                            player = p
                            break
            if not player:
                logger.info(f"结算跳过未维护用户: {claim_nick} wxid={wxid or '-'}")
                if include_invalid:
                    rows.append(
                        {
                            "nickname": claim_nick,
                            "wxid": wxid,
                            "bet_amount": float(bet.get("amount") or 0),
                            "packet_amount": 0.0,
                            "point": -1,
                            "has_claim": False,
                            "balance_before": 0.0,
                            "claim_name": "",
                            "is_valid": False,
                            "stats_only": True,
                            "note": bet.get("invalid_reason") or "下注无效余额为零 请上分",
                        }
                    )
                continue

            account_nick = str(player.get("nickname") or claim_nick).strip()
            # 结算图展示完整备注；余额账户名可能与备注相同或为 GUI 维护名
            display_nick = claim_nick or account_nick
            is_banker = bool(banker_key) and (
                _remark_match_key(claim_nick) == _remark_match_key(banker_name)
                or _norm_name(claim_nick) == banker_key
                or _norm_name(account_nick) == banker_key
            )
            # 红包按备注 #编号# 中间编号比对
            claim, claim_note, warns = resolve_packet_claim(
                claim_nick,
                claims,
                is_banker=is_banker,
            )
            self.last_warnings.extend(warns)
            packet = float(claim["amount"]) if claim else 0.0
            point = amount_to_point(packet) if claim else -1
            combo = amount_to_combo(packet) if claim else ""
            # 未抢包借用他人金额：不算抢包先后，同额必须排在真实抢到者后面
            claim_borrowed = bool(claim_note)
            order_index = -1
            if (
                claim
                and not claim_borrowed
                and claim.get("order_index") is not None
            ):
                try:
                    order_index = int(claim.get("order_index"))
                except (TypeError, ValueError):
                    order_index = -1
            note = ""
            if not is_valid:
                note = bet.get("invalid_reason") or "无效下注"
            elif claim_note:
                note = claim_note

            rows.append(
                {
                    # 报表展示完整备注；account_nickname 供余额写入
                    "nickname": display_nick,
                    "account_nickname": account_nick,
                    "wxid": wxid or player.get("wxid") or "",
                    "bet_amount": float(bet.get("amount") or 0),
                    "packet_amount": packet,
                    "point": point,
                    "combo": combo,
                    "order_index": order_index,
                    "claim_borrowed": claim_borrowed,
                    "has_claim": bool(claim),
                    "balance_before": float(player.get("balance") or 0),
                    "claim_name": (claim or {}).get("name") or "",
                    "is_valid": is_valid,
                    "stats_only": not is_valid,
                    "note": note,
                }
            )
        return rows

    def settle_no_banker(
        self,
        rows: List[Dict[str, Any]],
        rake_percent: float,
        digit_weight_order: str = "",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        无庄大吃小：先按总下注抽水，再按名次依次还本、赔付。

        排名：点数 → 组合（忽略顺序，按 0>9>…>1 先比最大位）→
        真实抢包优先于未抢包借用金额 → 完全相同则红包列表靠下者（先抢）优先。
        """
        _ = digit_weight_order  # 已废弃，保留参数兼容旧调用
        active = [r for r in rows if r.get("is_valid", True) and not r.get("stats_only")]
        stats_rows = [r for r in rows if r.get("stats_only") or not r.get("is_valid", True)]

        total_bet = sum(float(r["bet_amount"]) for r in active)
        # 先抽水：奖金池 = 总下注 − 总下注×X%
        rake = round(total_bet * float(rake_percent) / 100.0, 2)
        pool = round(total_bet - rake, 2)
        remain = pool

        def _rank_key(r: Dict[str, Any]) -> Tuple[Any, ...]:
            combo = r.get("combo") or amount_to_combo(float(r.get("packet_amount") or 0))
            idx = r.get("order_index")
            try:
                # 无位置/借用金额时用 -1，reverse 后排最后
                idx_i = int(idx) if idx is not None and int(idx) >= 0 else -1
            except (TypeError, ValueError):
                idx_i = -1
            # 点数/组合相同：真实抢包 > 借用；同为真实则靠下（先抢）优先
            return (
                1 if r.get("has_claim") else 0,
                int(r.get("point", -1)),
                combo_compare_key(combo),
                0 if r.get("claim_borrowed") else 1,
                idx_i,
            )

        ranked = sorted(active, key=_rank_key, reverse=True)

        stop_pay = False
        principal_sum = 0.0
        interim: List[Dict[str, Any]] = []

        for r in ranked:
            bet = float(r["bet_amount"])
            combo = r.get("combo") or amount_to_combo(float(r.get("packet_amount") or 0))
            extra_note = r.get("note") or ""
            principal = 0.0
            payout = 0.0
            paid = False

            if stop_pay or not r.get("has_claim") or remain <= 1e-9:
                note = "判负" if not combo else f"判负；组合{combo}"
                if not r.get("has_claim"):
                    note = "判负"
                stop_pay = True
            elif remain + 1e-9 >= bet:
                # 足够还本 → 还本后尽量 1 赔 1（剩多少赔多少）
                principal = bet
                remain = round(remain - principal, 2)
                principal_sum = round(principal_sum + principal, 2)
                payout = round(min(bet, remain), 2)
                remain = round(remain - payout, 2)
                paid = True
                if payout + 1e-9 >= bet:
                    note = f"还本{principal:.2f}+赔付{payout:.2f}；组合{combo}"
                else:
                    note = f"还本{principal:.2f}+部分赔付{payout:.2f}；组合{combo}"
                    stop_pay = True
            else:
                # 不够还本：剩余奖池全部给他，其后奖池为 0
                principal = round(remain, 2)
                remain = 0.0
                principal_sum = round(principal_sum + principal, 2)
                paid = True
                stop_pay = True
                note = f"部分还本{principal:.2f}；组合{combo}"

            interim.append(
                {
                    "src": r,
                    "bet": bet,
                    "combo": combo,
                    "extra_note": extra_note,
                    "paid": paid,
                    "principal": principal,
                    "payout": payout,
                    "note": note,
                    "refund": 0.0,
                }
            )

        # 不再把剩余奖池按比例返输家；不够还本时已在上面吃掉剩余
        refund_total = 0.0
        remain_after = remain

        result_rows: List[Dict[str, Any]] = []
        for x in interim:
            r = x["src"]
            bet = x["bet"]
            bal_before = float(r["balance_before"])
            principal = float(x["principal"])
            payout = float(x["payout"])
            refund = float(x["refund"])
            # 余额 = 旧 − 押注 + 还本 + 赔付
            bal_after = round(bal_before - bet + principal + payout + refund, 2)
            delta = round(bal_after - bal_before, 2)
            note = x["note"]
            if x["extra_note"]:
                note = f"{note}；{x['extra_note']}"
            result_rows.append(
                {
                    "seq": 0,
                    "nickname": r["nickname"],
                    "account_nickname": r.get("account_nickname") or r["nickname"],
                    "bet_amount": bet,
                    "packet_amount": r["packet_amount"],
                    "point": r["point"] if r["point"] >= 0 else "",
                    "combo": x["combo"],
                    "delta": delta,
                    "balance_before": bal_before,
                    "balance_after": bal_after,
                    "paid": x["paid"],
                    "principal": principal,
                    "payout": payout,
                    "refund": refund,
                    "note": note,
                    "stats_only": False,
                }
            )

        for r in stats_rows:
            result_rows.append(
                {
                    "seq": 0,
                    "nickname": r["nickname"],
                    "account_nickname": r.get("account_nickname") or r["nickname"],
                    "bet_amount": float(r.get("bet_amount") or 0),
                    "packet_amount": r.get("packet_amount") or 0,
                    "point": r["point"] if int(r.get("point", -1)) >= 0 else "",
                    "delta": 0.0,
                    "balance_before": float(r.get("balance_before") or 0),
                    "balance_after": float(r.get("balance_before") or 0),
                    "paid": False,
                    "note": r.get("note") or "无效/失败，仅统计",
                    "stats_only": True,
                }
            )

        for i, row in enumerate(result_rows, start=1):
            row["seq"] = i

        summary = {
            "mode": "无庄",
            "banker_name": "",
            "rake_percent": float(rake_percent),
            "total_bet": total_bet,
            "principal_returned": principal_sum,
            "rake_amount": rake,
            "pool_amount": pool,
            "pool_remain": remain_after,
            "loser_refund_total": round(refund_total, 2),
            "digit_strength_order": DIGIT_STRENGTH_ORDER,
            "warnings": list(self.last_warnings),
        }
        return result_rows, summary

    def settle_with_banker(
        self,
        rows: List[Dict[str, Any]],
        banker_name: str,
        claims: Optional[List[Dict[str, Any]]] = None,
        room_name: str = "",
        rake_percent: float = 0.0,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        有庄：每个有效闲家独立与庄家比点；同点庄胜；压多少赔多少。
        庄家不参与下注、不取采购数量，结算表只保留一条庄家汇总行；
        庄家自己的下注/失败记录一律忽略，不重复入表。
        比大小：先比点数；同点再比三数字组合（忽略顺序，0>9>…>1 先比最大位）；
        点数与组合都相同则庄胜。抽水额外从庄家余额扣除。
        """
        banker_key = _norm_name(banker_name)
        banker_id = _remark_match_key(banker_name)

        def _same_banker_name(nick: str) -> bool:
            nick = (nick or "").strip()
            if not nick:
                return False
            if banker_id and _remark_match_key(nick) == banker_id:
                return True
            return _norm_name(nick) == banker_key

        # 庄家本人的任何下注行（有效/无效）都排除，避免出现两条 chat
        def _is_banker_row(r: Dict[str, Any]) -> bool:
            if _same_banker_name(str(r.get("nickname") or "")):
                return True
            return _same_banker_name(str(r.get("account_nickname") or ""))

        non_banker_rows = [r for r in rows if not _is_banker_row(r)]
        active = [
            r
            for r in non_banker_rows
            if r.get("is_valid", True) and not r.get("stats_only")
        ]
        stats_rows = [
            r
            for r in non_banker_rows
            if r.get("stats_only") or not r.get("is_valid", True)
        ]
        players = active

        # 庄家只取抢包点数与余额，不取采购数量（支持备注编号关联账户）
        player = self.store.get_player(banker_name, room_name)
        if not player and banker_id:
            for p in self.store.list_players(room_name):
                if _remark_match_key(p.get("nickname") or "") == banker_id:
                    player = p
                    break
        if not player and banker_key:
            for p in self.store.list_players(room_name):
                if _norm_name(p.get("nickname") or "") == banker_key:
                    player = p
                    break
        if not player:
            raise ValueError(
                f"庄家未在用户表维护: {banker_name}\n"
                f"请先在余额页添加该用户，或填写与账户一致的备注/昵称"
            )

        def _safe_point(raw: Any) -> int:
            try:
                if raw is None or raw == "":
                    return -1
                return int(raw)
            except (TypeError, ValueError):
                return -1

        # 若 build_player_rows 已解析过庄家抢包，优先复用；否则现场解析
        banker_built = next(
            (
                r
                for r in rows
                if r.get("has_claim")
                and (
                    _same_banker_name(str(r.get("nickname") or ""))
                    or _same_banker_name(str(r.get("account_nickname") or ""))
                )
            ),
            None,
        )
        built_point = _safe_point((banker_built or {}).get("point", -1))
        if banker_built and built_point >= 0:
            banker = {
                "nickname": banker_name,
                "wxid": player.get("wxid") or "",
                "bet_amount": 0.0,
                "packet_amount": float(banker_built.get("packet_amount") or 0),
                "point": built_point,
                "has_claim": True,
                "balance_before": float(player.get("balance") or 0),
                "claim_name": banker_built.get("claim_name") or banker_name,
                "note": banker_built.get("note") or "",
                "is_valid": True,
            }
            # 若 note 是无效下注原因，清掉（庄家不看下注）
            if not banker_built.get("is_valid", True):
                banker["note"] = ""
        else:
            # 依次用填写名、账户名解析抢包（编号键可匹配 OCR 备注）
            claim = None
            claim_note = ""
            for cand in (
                banker_name,
                str(player.get("nickname") or ""),
            ):
                if not (cand or "").strip():
                    continue
                claim, claim_note, warns = resolve_packet_claim(
                    cand, claims or [], is_banker=True
                )
                self.last_warnings.extend(warns)
                if claim:
                    break
            if not claim:
                n_claims = len(claims or [])
                raise ValueError(
                    f"未找到庄家抢包记录且兜底失败: {banker_name}\n"
                    f"当前识别领取 {n_claims} 条；请确认截图完整，或庄家备注能对上领取列表"
                )
            banker = {
                "nickname": banker_name,
                "wxid": player.get("wxid") or "",
                "bet_amount": 0.0,
                "packet_amount": float(claim.get("amount") or 0),
                "point": amount_to_point(float(claim.get("amount") or 0)),
                "has_claim": True,
                "balance_before": float(player.get("balance") or 0),
                "claim_name": claim.get("name") or banker_name,
                "note": claim_note or "",
                "is_valid": True,
            }

        banker_point = int(banker.get("point", -1))
        banker_combo = amount_to_combo(float(banker.get("packet_amount") or 0))
        banker_delta = 0.0
        result_rows: List[Dict[str, Any]] = []

        for p in players:
            bet = float(p["bet_amount"])
            p_point = int(p.get("point", -1))
            p_combo = p.get("combo") or amount_to_combo(float(p.get("packet_amount") or 0))
            extra = p.get("note") or ""
            bal_before = float(p["balance_before"])
            principal = 0.0
            payout = 0.0
            # 有庄一对一：先比点数；同点再比组合；都相同庄胜
            # 超市余额 = 原余额 - 押注 + 本金 + 赔付（与无庄同一公式）
            if (
                not p.get("has_claim")
                or not banker.get("has_claim")
                or p_point < 0
                or banker_point < 0
            ):
                note = "缺点数记录，闲家负"
                paid = False
            elif p_point > banker_point:
                principal = bet
                payout = bet
                note = (
                    f"闲家{p_point}点 > 庄家{banker_point}点；"
                    f"还本{principal:.2f}+赔{payout:.2f}"
                )
                paid = True
            elif p_point < banker_point:
                note = f"闲家{p_point}点 < 庄家{banker_point}点，庄胜"
                paid = False
            elif combos_equal(p_combo, banker_combo):
                # 同点且三数字完全相同（忽略顺序）→ 庄胜
                note = (
                    f"同{p_point}点且组合相同"
                    f"（闲{p_combo}/庄{banker_combo}），庄胜"
                )
                paid = False
            elif combo_compare_key(p_combo) > combo_compare_key(banker_combo):
                principal = bet
                payout = bet
                note = (
                    f"同{p_point}点；组合闲{p_combo}>庄{banker_combo}；"
                    f"还本{principal:.2f}+赔{payout:.2f}"
                )
                paid = True
            else:
                note = (
                    f"同{p_point}点；组合闲{p_combo}<庄{banker_combo}，庄胜"
                )
                paid = False
            bal_after = round(bal_before - bet + principal + payout, 2)
            delta = round(bal_after - bal_before, 2)
            # 庄家盈亏与闲家相反（闲家 +200 则庄家 -200）
            banker_delta = round(banker_delta - delta, 2)
            if extra:
                note = f"{note}；{extra}"
            result_rows.append(
                {
                    "seq": 0,
                    "nickname": p["nickname"],
                    "account_nickname": p.get("account_nickname") or p["nickname"],
                    "bet_amount": bet,
                    "packet_amount": p["packet_amount"],
                    "point": p_point if p_point >= 0 else "",
                    "delta": delta,
                    "balance_before": bal_before,
                    "balance_after": bal_after,
                    "paid": paid,
                    "principal": principal,
                    "payout": payout,
                    "note": note,
                    "stats_only": False,
                    "is_banker": False,
                }
            )

        total_bet = round(sum(float(r["bet_amount"]) for r in players), 2)
        # 抽水额外扣庄家余额，不从押注里减（押注1万+5% → 另扣500）
        rake = round(total_bet * float(rake_percent or 0) / 100.0, 2)
        if rake:
            banker_delta = round(banker_delta - rake, 2)

        banker_note = "庄家"
        claim_note = (banker.get("note") or "").strip()
        # 仅保留抢包相关说明，不带下注失败原因；抽水金额不写入备注（图上不展示）
        if claim_note and "低于最低" not in claim_note and "无效" not in claim_note:
            banker_note = f"庄家；{claim_note}"
        banker_before = float(banker.get("balance_before") or 0)
        result_rows.insert(
            0,
            {
                "seq": 0,
                "nickname": banker.get("nickname") or banker_name,
                "account_nickname": str(player.get("nickname") or banker_name),
                "bet_amount": "庄家",  # 采购数量栏显示「庄家」，不取下注额
                "packet_amount": banker.get("packet_amount") or 0,
                "point": banker_point if banker_point >= 0 else "",
                "delta": round(banker_delta, 2),
                "balance_before": banker_before,
                "balance_after": round(banker_before + banker_delta, 2),
                "paid": banker_delta > 0,
                "note": banker_note,
                "stats_only": False,
                "is_banker": True,
            },
        )

        for r in stats_rows:
            result_rows.append(
                {
                    "seq": 0,
                    "nickname": r["nickname"],
                    "account_nickname": r.get("account_nickname") or r["nickname"],
                    "bet_amount": float(r.get("bet_amount") or 0),
                    "packet_amount": r.get("packet_amount") or 0,
                    "point": r["point"] if int(r.get("point", -1)) >= 0 else "",
                    "delta": 0.0,
                    "balance_before": float(r.get("balance_before") or 0),
                    "balance_after": float(r.get("balance_before") or 0),
                    "paid": False,
                    "note": r.get("note") or "无效/失败，仅统计",
                    "stats_only": True,
                    "is_banker": False,
                }
            )

        for i, row in enumerate(result_rows, start=1):
            row["seq"] = i

        summary = {
            "mode": "有庄",
            "banker_name": banker_name,
            "rake_percent": float(rake_percent or 0),
            "total_bet": total_bet,
            "rake_amount": rake,
            # 有庄：奖池仍为有效总下注；抽水是庄家额外支出，不从池内扣减
            "pool_amount": total_bet,
            "pool_remain": 0.0,
            "banker_delta": round(banker_delta, 2),
            "warnings": list(self.last_warnings),
        }
        return result_rows, summary

    def apply_and_save(
        self,
        round_id: int,
        room_name: str,
        result_rows: List[Dict[str, Any]],
        summary: Dict[str, Any],
    ) -> Path:
        """写入余额、落库报表行、导出报表。无效/统计行不改余额。"""
        for row in result_rows:
            # 报表用完整备注；扣余额用账户名（可能同为 #001#xxx）
            nick = row.get("account_nickname") or row["nickname"]
            delta = float(row["delta"])
            if row.get("stats_only"):
                continue
            if abs(delta) < 1e-9 and not row.get("paid"):
                # 庄家可能 delta=0；仅在有玩家账户时刷新展示
                player = self.store.get_player(nick, room_name)
                if player:
                    bal = round(float(player.get("balance") or 0), 2)
                    row["balance_before"] = bal
                    row["balance_after"] = bal
                continue
            if not self.store.get_player(nick, room_name):
                continue
            self.store.adjust_balance(
                nick,
                delta,
                room_name=room_name,
                type_="对局输赢",
                remark=row.get("note") or "本局结算",
                round_id=round_id,
                operator="system",
            )
            player = self.store.get_player(nick, room_name) or {}
            row["balance_after"] = round(
                float(player.get("balance") or row["balance_after"] or 0), 2
            )

        self.store.save_settlement_rows(round_id, result_rows)
        self.store.mark_round_settled(
            round_id=round_id,
            mode=summary.get("mode", ""),
            banker_name=summary.get("banker_name", ""),
            rake_percent=float(summary.get("rake_percent") or 0),
            total_bet=float(summary.get("total_bet") or 0),
            rake_amount=float(summary.get("rake_amount") or 0),
            pool_amount=float(summary.get("pool_amount") or 0),
        )

        report_path = self._export_report(round_id, room_name, result_rows, summary)
        self.store.mark_round_settled(
            round_id=round_id,
            mode=summary.get("mode", ""),
            banker_name=summary.get("banker_name", ""),
            rake_percent=float(summary.get("rake_percent") or 0),
            total_bet=float(summary.get("total_bet") or 0),
            rake_amount=float(summary.get("rake_amount") or 0),
            pool_amount=float(summary.get("pool_amount") or 0),
            report_path=str(report_path),
        )
        return report_path

    def _export_report(
        self,
        round_id: int,
        room_name: str,
        result_rows: List[Dict[str, Any]],
        summary: Dict[str, Any],
    ) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_room = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", room_name) or "room"
        stem = f"settle_{safe_room}_{round_id}_{ts}"
        # 奖池总额=未抽水前有效总下注（图头左侧；口号居中）
        pool_before_rake = round(float(summary.get("total_bet") or 0), 2)
        SLOGAN = "明细实时记录｜无遗漏丢失"
        payload = {
            "round_id": round_id,
            "room_name": room_name,
            "summary": summary,
            "slogan": SLOGAN,
            "pool_before_rake": pool_before_rake,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rows": [
                {
                    "序号": r["seq"],
                    "用户": r["nickname"],
                    "采购数量": (
                        "庄家"
                        if r.get("is_banker") or r.get("bet_amount") == "庄家"
                        else round(float(r.get("bet_amount") or 0), 2)
                    ),
                    "采购结果": r["point"],
                    "红包金额": round(float(r.get("packet_amount") or 0), 2),
                    "采购加减": round(float(r.get("delta") or 0), 2),
                    "超市余额": round(float(r.get("balance_before") or 0), 2),
                    "剩余": round(float(r.get("balance_after") or 0), 2),
                    "备注": r.get("note", ""),
                    # 无效行、不足赔付/判输（负加减如 -50）红色高亮
                    "_invalid": bool(r.get("stats_only"))
                    or float(r.get("delta") or 0) < -1e-9,
                }
                for r in result_rows
            ],
        }
        json_path = self.report_dir / f"{stem}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        fieldnames = [
            "序号",
            "用户",
            "采购数量",
            "采购结果",
            "红包金额",
            "采购加减",
            "超市余额",
            "剩余",
            "备注",
        ]
        csv_path = self.report_dir / f"{stem}.csv"
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in payload["rows"]:
                writer.writerow(row)

        xlsx_path = self.report_dir / f"{stem}.xlsx"
        # 后台/本地 Excel：保留群名、总下注、抽水等完整表头
        self._export_styled_xlsx(
            xlsx_path, payload["rows"], fieldnames, summary, room_name
        )
        png_path = self.report_dir / f"{stem}.png"
        appendix_rows = self._idle_balance_appendix_rows(
            room_name, result_rows, fieldnames
        )
        # 发群图片：左侧奖池总额，口号居中；下方分隔未下注有余额用户
        self._export_table_image(
            png_path,
            payload["rows"],
            fieldnames,
            slogan=SLOGAN,
            pool_before_rake=pool_before_rake,
            appendix_rows=appendix_rows,
            appendix_label="未下注 · 仍有余额",
        )
        logger.info(f"结算报表已生成: xlsx={xlsx_path} png={png_path}")
        # 发群用图片
        return png_path

    def _idle_balance_appendix_rows(
        self,
        room_name: str,
        result_rows: List[Dict[str, Any]],
        fieldnames: List[str],
    ) -> List[Dict[str, Any]]:
        """结算图附录：本局未出现、但账户仍有余额的用户。"""
        involved: set[str] = set()
        for r in result_rows:
            for key in (
                str(r.get("nickname") or ""),
                str(r.get("account_nickname") or ""),
            ):
                key = key.strip()
                if not key:
                    continue
                involved.add(_norm_name(key))
                rk = _remark_match_key(key)
                if rk:
                    involved.add(rk)

        appendix: List[Dict[str, Any]] = []
        seq = 1
        for p in self.store.list_players(room_name):
            bal = round(float(p.get("balance") or 0), 2)
            if bal <= 1e-9:
                continue
            nick = str(p.get("nickname") or "").strip()
            if not nick:
                continue
            keys = {_norm_name(nick)}
            rk = _remark_match_key(nick)
            if rk:
                keys.add(rk)
            if keys & involved:
                continue
            row: Dict[str, Any] = {name: "" for name in fieldnames}
            row["序号"] = seq
            if "用户" in row:
                row["用户"] = nick
            elif "用户账号 ID" in row:
                row["用户账号 ID"] = nick
            if "采购数量" in row:
                row["采购数量"] = "-"
            if "采购结果" in row:
                row["采购结果"] = "-"
            if "红包金额" in row:
                row["红包金额"] = "-"
            if "采购加减" in row:
                row["采购加减"] = 0.0
            if "超市余额" in row:
                row["超市余额"] = bal
            if "剩余" in row:
                row["剩余"] = bal
            if "备注" in row:
                row["备注"] = "未下注"
            row["_appendix"] = True
            appendix.append(row)
            seq += 1
        return appendix

    def _export_styled_xlsx(
        self,
        path: Path,
        rows: List[Dict[str, Any]],
        fieldnames: List[str],
        summary: Dict[str, Any],
        room_name: str,
    ) -> None:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = "结算报表"

        header_fill = PatternFill("solid", fgColor="1F4E79")
        header_font = Font(bold=True, color="FFFFFF", size=12, name="微软雅黑")
        white_fill = PatternFill("solid", fgColor="FFFFFF")
        blue_fill = PatternFill("solid", fgColor="DDEBF7")
        red_fill = PatternFill("solid", fgColor="FFC7CE")
        red_font = Font(size=11, name="微软雅黑", color="9C0006")
        title_font = Font(bold=True, size=14, name="微软雅黑", color="1F4E79")
        cell_font = Font(size=11, name="微软雅黑")
        thin = Border(
            left=Side(style="thin", color="B4B4B4"),
            right=Side(style="thin", color="B4B4B4"),
            top=Side(style="thin", color="B4B4B4"),
            bottom=Side(style="thin", color="B4B4B4"),
        )
        center = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ws.merge_cells(
            start_row=1, start_column=1, end_row=1, end_column=len(fieldnames)
        )
        mode = summary.get("mode") or ""
        if mode in ("no_banker",):
            mode = "无庄"
        elif mode in ("banker",):
            mode = "有庄"
        title = (
            f"{room_name} 结算报表  "
            f"模式={mode}  "
            f"总下注={summary.get('total_bet')}  "
            f"抽水={summary.get('rake_amount')}  "
            f"奖金池={summary.get('pool_amount')}"
        )
        if summary.get("banker_name"):
            title += f"  庄家={summary.get('banker_name')}"
        ws["A1"] = title
        ws["A1"].font = title_font
        ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[1].height = 28

        header_row = 3
        for col, name in enumerate(fieldnames, start=1):
            cell = ws.cell(row=header_row, column=col, value=name)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center
            cell.border = thin
        ws.row_dimensions[header_row].height = 24

        for i, row in enumerate(rows):
            excel_row = header_row + 1 + i
            invalid = bool(row.get("_invalid"))
            fill = red_fill if invalid else (white_fill if i % 2 == 0 else blue_fill)
            font = red_font if invalid else cell_font
            for col, name in enumerate(fieldnames, start=1):
                value = row.get(name, "")
                if name == "采购加减" and isinstance(value, (int, float)):
                    value = f"{float(value):+.2f}"
                elif name in ("超市余额", "剩余", "红包金额", "采购数量") and isinstance(
                    value, (int, float)
                ):
                    value = f"{float(value):.2f}"
                cell = ws.cell(row=excel_row, column=col, value=value)
                cell.fill = fill
                cell.font = font
                cell.alignment = center
                cell.border = thin
            ws.row_dimensions[excel_row].height = 22

        col_widths = {
            "序号": 8,
            "用户": 18,
            "采购数量": 12,
            "采购结果": 12,
            "红包金额": 12,
            "采购加减": 12,
            "超市余额": 12,
            "剩余": 12,
            "备注": 28,
        }
        for col, name in enumerate(fieldnames, start=1):
            ws.column_dimensions[get_column_letter(col)].width = col_widths.get(name, 14)

        ws.freeze_panes = "A4"
        wb.save(path)

    def _export_table_image(
        self,
        path: Path,
        rows: List[Dict[str, Any]],
        fieldnames: List[str],
        slogan: str = "明细实时记录｜无遗漏丢失",
        pool_before_rake: Optional[float] = None,
        left_text: Optional[str] = None,
        right_text: Optional[str] = None,
        tip_text: Optional[str] = None,
        appendix_rows: Optional[List[Dict[str, Any]]] = None,
        appendix_label: str = "未下注 · 仍有余额",
    ) -> Path:
        """将结算/核对表渲染为图片。表头左/中/右可配；可附带提示条与分隔附录区。"""
        from PIL import Image, ImageDraw, ImageFont

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        appendix_rows = list(appendix_rows or [])
        tip_text = (tip_text or "").strip()

        def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
            candidates = [
                "msyhbd.ttc" if bold else "msyh.ttc",
                "msyh.ttc",
                "simhei.ttf",
                "simsun.ttc",
                "arial.ttf",
            ]
            windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
            for name in candidates:
                fp = windir / name
                if fp.exists():
                    try:
                        return ImageFont.truetype(str(fp), size)
                    except OSError:
                        continue
            return ImageFont.load_default()

        title_font = _font(22, bold=True)
        tip_font = _font(16, bold=True)
        header_font = _font(18, bold=True)
        cell_font = _font(16)
        sep_font = _font(16, bold=True)
        pad_x, pad_y = 12, 8
        row_h = 36
        title_h = 56
        tip_h = 34 if tip_text else 0
        sep_h = 34
        left_pad = 14
        right_pad = 14
        if left_text is None and pool_before_rake is not None:
            left_text = f"奖池总额 {float(pool_before_rake):g}"
        left_text = left_text or ""
        right_text = right_text or ""

        def _cell_text(row: Dict[str, Any], name: str) -> str:
            value = row.get(name, "")
            if value is None:
                return ""
            if name == "采购加减" and isinstance(value, (int, float)):
                return f"{float(value):+.2f}"
            if name in ("超市余额", "剩余", "红包金额", "采购数量", "下注金额") and isinstance(
                value, (int, float)
            ):
                return f"{float(value):.2f}"
            return str(value)

        # 列宽按内容估算（含附录行）
        all_content_rows = list(rows) + appendix_rows
        col_widths: List[int] = []
        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        for name in fieldnames:
            max_w = probe.textlength(name, font=header_font)
            for row in all_content_rows:
                max_w = max(max_w, probe.textlength(_cell_text(row, name), font=cell_font))
            col_widths.append(int(max_w) + pad_x * 2)

        slogan_w = int(probe.textlength(slogan, font=title_font))
        left_w = int(probe.textlength(left_text, font=title_font)) if left_text else 0
        right_w = int(probe.textlength(right_text, font=title_font)) if right_text else 0
        tip_w = int(probe.textlength(tip_text, font=tip_font)) if tip_text else 0
        side_w = max(left_w, right_w)
        need_w = max(
            slogan_w + side_w * 2 + left_pad + right_pad + 24,
            slogan_w + left_w + right_w + left_pad + right_pad + 40,
            tip_w + left_pad * 2 + 24,
            slogan_w + 48,
        )
        table_w = max(sum(col_widths), need_w)
        extra = table_w - sum(col_widths)
        if extra > 0 and col_widths:
            col_widths[-1] += extra

        has_appendix = bool(appendix_rows)
        head_h = title_h + tip_h
        table_h = head_h + row_h * (1 + len(rows))
        if has_appendix:
            table_h += sep_h + row_h * len(appendix_rows)
        img = Image.new("RGB", (table_w + 2, table_h + 2), "#FFFFFF")
        draw = ImageDraw.Draw(img)

        # 表头标语行：左 / 中 / 右
        draw.rectangle([0, 0, table_w, title_h], fill="#FFF2CC")
        ty = (title_h - 22) / 2
        if left_text:
            draw.text((left_pad, ty), left_text, fill="#C00000", font=title_font)
        tw = probe.textlength(slogan, font=title_font)
        draw.text(
            ((table_w - tw) / 2, ty),
            slogan,
            fill="#C00000",
            font=title_font,
        )
        if right_text:
            draw.text(
                (table_w - right_w - right_pad, ty),
                right_text,
                fill="#C00000",
                font=title_font,
            )

        # 当庄不足等提示条
        if tip_text:
            draw.rectangle([0, title_h, table_w, title_h + tip_h], fill="#FCE4D6")
            draw.line([(0, title_h), (table_w, title_h)], fill="#C65911", width=1)
            # 过长则截断
            shown = tip_text
            while (
                shown
                and probe.textlength(shown, font=tip_font) > table_w - left_pad * 2
            ):
                shown = shown[:-2]
            if shown != tip_text and shown:
                shown = shown[:-1] + "…"
            draw.text(
                (left_pad, title_h + (tip_h - 18) / 2),
                shown,
                fill="#C65911",
                font=tip_font,
            )

        def _draw_header_row(y0: int) -> None:
            x0 = 0
            for i, name in enumerate(fieldnames):
                draw.rectangle(
                    [x0, y0, x0 + col_widths[i], y0 + row_h],
                    fill="#1F4E79",
                    outline="#B4B4B4",
                )
                cw = probe.textlength(name, font=header_font)
                draw.text(
                    (x0 + (col_widths[i] - cw) / 2, y0 + pad_y),
                    name,
                    fill="#FFFFFF",
                    font=header_font,
                )
                x0 += col_widths[i]

        def _draw_data_rows(start_y: int, data_rows: List[Dict[str, Any]]) -> None:
            for ri, row in enumerate(data_rows):
                y0 = start_y + row_h * ri
                invalid = bool(row.get("_invalid"))
                appendix = bool(row.get("_appendix"))
                if invalid:
                    bg, fg = "#FFC7CE", "#9C0006"
                elif appendix:
                    # 未下注附录：青绿底 + 深蓝字，避免黑黄对比不清
                    bg = "#E6F7F1" if ri % 2 == 0 else "#D0EFE4"
                    fg = "#0B3D5C"
                else:
                    bg = "#FFFFFF" if ri % 2 == 0 else "#DDEBF7"
                    fg = "#000000"
                x0 = 0
                for i, name in enumerate(fieldnames):
                    text = _cell_text(row, name)
                    draw.rectangle(
                        [x0, y0, x0 + col_widths[i], y0 + row_h],
                        fill=bg,
                        outline="#B4B4B4",
                    )
                    cw = probe.textlength(text, font=cell_font)
                    draw.text(
                        (x0 + (col_widths[i] - cw) / 2, y0 + pad_y),
                        text,
                        fill=fg,
                        font=cell_font,
                    )
                    x0 += col_widths[i]

        # 表头 + 主数据
        _draw_header_row(head_h)
        _draw_data_rows(head_h + row_h, rows)

        # 分隔 + 附录（未下注有余额）
        if has_appendix:
            sep_y = head_h + row_h * (1 + len(rows))
            draw.rectangle([0, sep_y, table_w, sep_y + sep_h], fill="#B8E0D2")
            draw.line([(0, sep_y), (table_w, sep_y)], fill="#2A6F97", width=2)
            draw.line(
                [(0, sep_y + sep_h - 1), (table_w, sep_y + sep_h - 1)],
                fill="#2A6F97",
                width=1,
            )
            sw = probe.textlength(appendix_label, font=sep_font)
            draw.text(
                ((table_w - sw) / 2, sep_y + (sep_h - 18) / 2),
                appendix_label,
                fill="#0B3D5C",
                font=sep_font,
            )
            _draw_data_rows(sep_y + sep_h, appendix_rows)

        img.save(path, format="PNG")
        return path
