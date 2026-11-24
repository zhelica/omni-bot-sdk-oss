"""游戏本地持久化：玩家余额、对局、下注、流水。"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _money(value: Any) -> float:
    """金额统一保留 2 位小数，避免浮点尾巴。"""
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


class GameStore:
    """SQLite 存储，线程安全。"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nickname TEXT NOT NULL,
                    wxid TEXT DEFAULT '',
                    room_name TEXT DEFAULT '',
                    balance REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(nickname, room_name)
                );

                CREATE TABLE IF NOT EXISTS rounds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'collecting',
                    mode TEXT DEFAULT '',
                    banker_name TEXT DEFAULT '',
                    rake_percent REAL DEFAULT 0,
                    total_bet REAL DEFAULT 0,
                    rake_amount REAL DEFAULT 0,
                    pool_amount REAL DEFAULT 0,
                    report_path TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_id INTEGER NOT NULL,
                    nickname TEXT NOT NULL,
                    wxid TEXT DEFAULT '',
                    amount REAL NOT NULL DEFAULT 0,
                    content TEXT DEFAULT '',
                    is_valid INTEGER NOT NULL DEFAULT 1,
                    invalid_reason TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(round_id, nickname),
                    FOREIGN KEY(round_id) REFERENCES rounds(id)
                );

                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nickname TEXT NOT NULL,
                    room_name TEXT DEFAULT '',
                    change_amount REAL NOT NULL,
                    balance_before REAL NOT NULL,
                    balance_after REAL NOT NULL,
                    type TEXT NOT NULL,
                    remark TEXT DEFAULT '',
                    round_id INTEGER,
                    operator TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settlement_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_id INTEGER NOT NULL,
                    seq INTEGER NOT NULL,
                    nickname TEXT NOT NULL,
                    bet_amount REAL NOT NULL,
                    packet_amount REAL DEFAULT 0,
                    point INTEGER DEFAULT 0,
                    delta REAL NOT NULL,
                    balance_before REAL NOT NULL,
                    balance_after REAL NOT NULL,
                    paid INTEGER NOT NULL DEFAULT 0,
                    note TEXT DEFAULT '',
                    FOREIGN KEY(round_id) REFERENCES rounds(id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS game_rooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(ledger)").fetchall()
            }
            if "operator" not in cols:
                conn.execute("ALTER TABLE ledger ADD COLUMN operator TEXT DEFAULT ''")
            # 默认数字组合权重：左侧更强，0>1>2>...>9
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", ("digit_weight_order",)
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?)",
                    ("digit_weight_order", "0123456789", _now()),
                )

    # ---------- players / balance ----------

    def list_players(self, room_name: str = "") -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if room_name:
                rows = conn.execute(
                    "SELECT * FROM players WHERE room_name=? ORDER BY nickname",
                    (room_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM players ORDER BY room_name, nickname"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_player(self, nickname: str, room_name: str = "") -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM players WHERE nickname=? AND room_name=? LIMIT 1",
                (nickname, room_name),
            ).fetchone()
            return dict(row) if row else None

    def ensure_player(
        self, nickname: str, room_name: str = "", wxid: str = "", balance: float = 0.0
    ) -> Dict[str, Any]:
        existing = self.get_player(nickname, room_name)
        if existing:
            if wxid and not existing.get("wxid"):
                with self._conn() as conn:
                    conn.execute(
                        "UPDATE players SET wxid=?, updated_at=? WHERE id=?",
                        (wxid, _now(), existing["id"]),
                    )
                existing["wxid"] = wxid
            return existing
        bal = _money(balance)
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO players(nickname, wxid, room_name, balance, updated_at) "
                "VALUES(?,?,?,?,?)",
                (nickname, wxid or "", room_name or "", bal, _now()),
            )
            pid = cur.lastrowid
        return self.get_player(nickname, room_name) or {
            "id": pid,
            "nickname": nickname,
            "balance": bal,
            "room_name": room_name,
            "wxid": wxid,
        }

    def set_balance(
        self,
        nickname: str,
        balance: float,
        room_name: str = "",
        remark: str = "后台调账",
        operator: str = "gui",
    ) -> Dict[str, Any]:
        player = self.ensure_player(nickname, room_name)
        before = _money(player["balance"])
        after = _money(balance)
        change = _money(after - before)
        if change > 0:
            typ = "上分"
        elif change < 0:
            typ = "下分"
        else:
            typ = "后台人工调账"
        with self._conn() as conn:
            conn.execute(
                "UPDATE players SET balance=?, updated_at=? WHERE id=?",
                (after, _now(), player["id"]),
            )
            conn.execute(
                "INSERT INTO ledger(nickname, room_name, change_amount, balance_before, "
                "balance_after, type, remark, operator, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    nickname,
                    room_name,
                    change,
                    before,
                    after,
                    typ,
                    remark,
                    operator,
                    _now(),
                ),
            )
        return self.get_player(nickname, room_name) or player

    def adjust_balance(
        self,
        nickname: str,
        delta: float,
        room_name: str = "",
        type_: str = "后台人工调账",
        remark: str = "",
        round_id: Optional[int] = None,
        operator: str = "gui",
    ) -> Dict[str, Any]:
        player = self.ensure_player(nickname, room_name)
        before = _money(player["balance"])
        change = _money(delta)
        after = _money(before + change)
        with self._conn() as conn:
            conn.execute(
                "UPDATE players SET balance=?, updated_at=? WHERE id=?",
                (after, _now(), player["id"]),
            )
            conn.execute(
                "INSERT INTO ledger(nickname, room_name, change_amount, balance_before, "
                "balance_after, type, remark, round_id, operator, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    nickname,
                    room_name,
                    change,
                    before,
                    after,
                    type_,
                    remark,
                    round_id,
                    operator,
                    _now(),
                ),
            )
        return self.get_player(nickname, room_name) or player

    def delete_player(self, nickname: str, room_name: str = "") -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM players WHERE nickname=? AND room_name=?",
                (nickname, room_name),
            )
            return cur.rowcount > 0

    def add_player(
        self, nickname: str, balance: float = 0.0, room_name: str = "", wxid: str = ""
    ) -> Dict[str, Any]:
        existing = self.get_player(nickname, room_name)
        if existing:
            raise ValueError(f"玩家已存在: {nickname}")
        return self.ensure_player(nickname, room_name, wxid, balance)

    def rename_player(
        self, old_nickname: str, new_nickname: str, room_name: str = ""
    ) -> Dict[str, Any]:
        """修改用户昵称，并同步本群流水/下注/结算行中的同名记录。"""
        old_nickname = (old_nickname or "").strip()
        new_nickname = (new_nickname or "").strip()
        if not old_nickname:
            raise ValueError("原用户名不能为空")
        if not new_nickname:
            raise ValueError("新用户名不能为空")
        player = self.get_player(old_nickname, room_name)
        if not player:
            raise ValueError(f"用户不存在: {old_nickname}")
        if old_nickname == new_nickname:
            return player
        if self.get_player(new_nickname, room_name):
            raise ValueError(f"用户已存在: {new_nickname}")
        with self._conn() as conn:
            conn.execute(
                "UPDATE players SET nickname=?, updated_at=? WHERE nickname=? AND room_name=?",
                (new_nickname, _now(), old_nickname, room_name),
            )
            conn.execute(
                "UPDATE ledger SET nickname=? WHERE nickname=? AND room_name=?",
                (new_nickname, old_nickname, room_name),
            )
            conn.execute(
                "UPDATE bets SET nickname=? WHERE nickname=? AND round_id IN "
                "(SELECT id FROM rounds WHERE room_name=?)",
                (new_nickname, old_nickname, room_name),
            )
            conn.execute(
                "UPDATE settlement_rows SET nickname=? WHERE nickname=? AND round_id IN "
                "(SELECT id FROM rounds WHERE room_name=?)",
                (new_nickname, old_nickname, room_name),
            )
            conn.execute(
                "UPDATE rounds SET banker_name=? WHERE banker_name=? AND room_name=?",
                (new_nickname, old_nickname, room_name),
            )
        return self.get_player(new_nickname, room_name) or player

    def upsert_player(
        self,
        nickname: str,
        balance: float,
        room_name: str = "",
        wxid: str = "",
        remark: str = "余额导入覆盖",
        operator: str = "gui",
    ) -> str:
        """导入用：不存在则新增，存在则覆盖余额（可选更新 wxid）。返回 created/updated。"""
        existing = self.get_player(nickname, room_name)
        if existing:
            self.set_balance(
                nickname, float(balance), room_name, remark=remark, operator=operator
            )
            if wxid:
                with self._conn() as conn:
                    conn.execute(
                        "UPDATE players SET wxid=?, updated_at=? WHERE nickname=? AND room_name=?",
                        (wxid, _now(), nickname, room_name),
                    )
            return "updated"
        self.ensure_player(nickname, room_name, wxid=wxid, balance=float(balance))
        return "created"

    # ---------- rounds / bets ----------

    def get_active_round(self, room_name: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM rounds WHERE room_name=? AND status='collecting' "
                "ORDER BY id DESC LIMIT 1",
                (room_name,),
            ).fetchone()
            return dict(row) if row else None

    def get_latest_ended_round(self, room_name: str = "") -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            if room_name:
                row = conn.execute(
                    "SELECT * FROM rounds WHERE room_name=? AND status IN ('ended','settled') "
                    "ORDER BY id DESC LIMIT 1",
                    (room_name,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM rounds WHERE status IN ('ended','settled') "
                    "ORDER BY id DESC LIMIT 1"
                ).fetchone()
            return dict(row) if row else None

    def get_round(self, round_id: int) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM rounds WHERE id=? LIMIT 1", (round_id,)
            ).fetchone()
            return dict(row) if row else None

    def start_round(self, room_name: str) -> Dict[str, Any]:
        active = self.get_active_round(room_name)
        if active:
            return active
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO rounds(room_name, started_at, status, created_at) "
                "VALUES(?,?,?,?)",
                (room_name, _now(), "collecting", _now()),
            )
            rid = cur.lastrowid
        return self.get_round(rid)  # type: ignore

    def end_round(self, room_name: str) -> Optional[Dict[str, Any]]:
        active = self.get_active_round(room_name)
        if not active:
            return None
        with self._conn() as conn:
            conn.execute(
                "UPDATE rounds SET status='ended', ended_at=? WHERE id=?",
                (_now(), active["id"]),
            )
        return self.get_round(active["id"])

    def set_bet_validity(
        self,
        round_id: int,
        nickname: str,
        is_valid: bool,
        invalid_reason: str = "",
    ) -> Optional[Dict[str, Any]]:
        """人工覆盖本局下注有效性（优先于）人工覆盖本局下注有效性（优先于系统自动判定）。"""
        nickname = (nickname or "").strip()
        if not nickname:
            return None
        reason = "" if is_valid else (invalid_reason or "人工判定无效")
        if is_valid:
            reason = ""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE bets SET is_valid=?, invalid_reason=?, updated_at=? "
                "WHERE round_id=? AND nickname=?",
                (1 if is_valid else 0, reason, _now(), round_id, nickname),
            )
            if cur.rowcount <= 0:
                return None
            row = conn.execute(
                "SELECT * FROM bets WHERE round_id=? AND nickname=? LIMIT 1",
                (round_id, nickname),
            ).fetchone()
            return dict(row) if row else None

    def void_round(self, round_id: int, reason: str = "作废局，下注不计") -> Dict[str, Any]:
        """
        手动作废本局：所有下注改为无效且不参与结算。
        当前流程下注时不预扣余额，故无需返还金额；作废后禁止再结算。
        """
        rnd = self.get_round(round_id)
        if not rnd:
            raise ValueError(f"对局不存在: {round_id}")
        status = str(rnd.get("status") or "")
        if status == "settled":
            raise ValueError(f"局#{round_id} 已结算，不能作废")
        if status == "voided":
            return rnd
        note = (reason or "作废局，下注不计").strip()
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "UPDATE rounds SET status='voided', ended_at=? WHERE id=?",
                (now, round_id),
            )
            conn.execute(
                "UPDATE bets SET is_valid=0, invalid_reason=?, updated_at=? WHERE round_id=?",
                (note, now, round_id),
            )
        return self.get_round(round_id) or rnd

    def upsert_bet(
        self,
        round_id: int,
        nickname: str,
        amount: float,
        wxid: str = "",
        content: str = "",
        is_valid: bool = True,
        invalid_reason: str = "",
    ) -> Dict[str, Any]:
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO bets(round_id, nickname, wxid, amount, content, is_valid, "
                "invalid_reason, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(round_id, nickname) DO UPDATE SET "
                "wxid=excluded.wxid, amount=excluded.amount, content=excluded.content, "
                "is_valid=excluded.is_valid, invalid_reason=excluded.invalid_reason, "
                "updated_at=excluded.updated_at",
                (
                    round_id,
                    nickname,
                    wxid,
                    float(amount),
                    content,
                    1 if is_valid else 0,
                    invalid_reason,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM bets WHERE round_id=? AND nickname=? LIMIT 1",
                (round_id, nickname),
            ).fetchone()
            return dict(row) if row else {}

    def list_bets(self, round_id: int, valid_only: bool = False) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if valid_only:
                rows = conn.execute(
                    "SELECT * FROM bets WHERE round_id=? AND is_valid=1 ORDER BY updated_at",
                    (round_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM bets WHERE round_id=? ORDER BY updated_at",
                    (round_id,),
                ).fetchall()
            return [dict(r) for r in rows]

    def list_rounds(self, room_name: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if room_name:
                rows = conn.execute(
                    "SELECT * FROM rounds WHERE room_name=? ORDER BY id DESC LIMIT ?",
                    (room_name, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM rounds ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def mark_round_settled(
        self,
        round_id: int,
        mode: str,
        banker_name: str,
        rake_percent: float,
        total_bet: float,
        rake_amount: float,
        pool_amount: float,
        report_path: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE rounds SET status='settled', mode=?, banker_name=?, rake_percent=?, "
                "total_bet=?, rake_amount=?, pool_amount=?, report_path=? WHERE id=?",
                (
                    mode,
                    banker_name,
                    float(rake_percent),
                    float(total_bet),
                    float(rake_amount),
                    float(pool_amount),
                    report_path,
                    round_id,
                ),
            )

    def rollback_settled_round(self, round_id: int) -> Dict[str, Any]:
        """
        回退已结算本局：按流水净变动恢复余额，清空结算行，局状态改回 ended，
        便于重新上传红包截图再结算。
        """
        rnd = self.get_round(round_id)
        if not rnd:
            raise ValueError(f"对局不存在: {round_id}")
        if str(rnd.get("status") or "") != "settled":
            raise ValueError(f"局#{round_id} 不是已结算状态，无法回退")

        room_name = str(rnd.get("room_name") or "")
        with self._conn() as conn:
            nets = conn.execute(
                "SELECT nickname, COALESCE(SUM(change_amount), 0) AS net "
                "FROM ledger WHERE round_id=? AND type IN ('对局输赢', '结算回退') "
                "GROUP BY nickname",
                (round_id,),
            ).fetchall()

        restored = 0
        for row in nets:
            nick = str(row["nickname"] or "").strip()
            net = _money(row["net"])
            if not nick or abs(net) < 1e-9:
                continue
            self.adjust_balance(
                nick,
                -net,
                room_name=room_name,
                type_="结算回退",
                remark=f"回退局#{round_id}结算",
                round_id=round_id,
                operator="gui",
            )
            restored += 1

        with self._conn() as conn:
            conn.execute("DELETE FROM settlement_rows WHERE round_id=?", (round_id,))
            conn.execute(
                "UPDATE rounds SET status='ended', mode='', banker_name='', "
                "rake_percent=0, total_bet=0, rake_amount=0, pool_amount=0, "
                "report_path='' WHERE id=?",
                (round_id,),
            )
        out = self.get_round(round_id) or rnd
        out["_rollback_players"] = restored
        return out

    def save_settlement_rows(self, round_id: int, rows: List[Dict[str, Any]]) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM settlement_rows WHERE round_id=?", (round_id,))
            for row in rows:
                raw_bet = row.get("bet_amount", 0)
                try:
                    # 庄家行采购数量为「庄家」文案，库内存 0
                    bet_amount = (
                        0.0
                        if row.get("is_banker") or raw_bet == "庄家"
                        else float(raw_bet or 0)
                    )
                except (TypeError, ValueError):
                    bet_amount = 0.0
                point_raw = row.get("point", 0)
                try:
                    point_val = int(point_raw) if point_raw != "" and point_raw is not None else 0
                except (TypeError, ValueError):
                    point_val = 0
                conn.execute(
                    "INSERT INTO settlement_rows(round_id, seq, nickname, bet_amount, "
                    "packet_amount, point, delta, balance_before, balance_after, paid, note) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        round_id,
                        row.get("seq", 0),
                        row.get("nickname", ""),
                        bet_amount,
                        float(row.get("packet_amount", 0) or 0),
                        point_val,
                        float(row.get("delta", 0) or 0),
                        float(row.get("balance_before", 0) or 0),
                        float(row.get("balance_after", 0) or 0),
                        1 if row.get("paid") else 0,
                        row.get("note", ""),
                    ),
                )

    def list_settlement_rows(self, round_id: int) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM settlement_rows WHERE round_id=? ORDER BY seq",
                (round_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_player_settlement_history(
        self,
        nickname: str,
        room_name: str = "",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """用户对局流水：局号、时间、模式、结算前后余额、加减等。"""
        sql = (
            "SELECT sr.round_id, sr.seq, sr.nickname, sr.bet_amount, sr.packet_amount, "
            "sr.point, sr.delta, sr.balance_before, sr.balance_after, sr.paid, sr.note, "
            "r.room_name, r.started_at, r.ended_at, r.mode, r.banker_name, "
            "r.total_bet, r.rake_amount, r.pool_amount "
            "FROM settlement_rows sr "
            "JOIN rounds r ON r.id = sr.round_id "
            "WHERE sr.nickname=?"
        )
        params: list = [nickname]
        if room_name:
            sql += " AND r.room_name=?"
            params.append(room_name)
        sql += " ORDER BY sr.round_id DESC, sr.seq ASC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]

    def get_bet(self, round_id: int, nickname: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM bets WHERE round_id=? AND nickname=? LIMIT 1",
                (round_id, nickname),
            ).fetchone()
            return dict(row) if row else None

    # ---------- 后台统计 ----------

    def list_ledger(
        self,
        room_name: str = "",
        nickname: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM ledger WHERE 1=1"
        params: list = []
        if room_name:
            sql += " AND room_name=?"
            params.append(room_name)
        if nickname:
            sql += " AND nickname=?"
            params.append(nickname)
        if date_from:
            sql += " AND created_at>=?"
            params.append(date_from)
        if date_to:
            sql += " AND created_at<=?"
            params.append(date_to + " 23:59:59" if len(date_to) == 10 else date_to)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]

    def list_rake_ledger(
        self, room_name: str = "", date_from: str = "", date_to: str = ""
    ) -> List[Dict[str, Any]]:
        """单局抽水台账（已结算局）。"""
        sql = (
            "SELECT id, room_name, started_at, ended_at, mode, banker_name, "
            "rake_percent, total_bet, rake_amount, pool_amount, status "
            "FROM rounds WHERE status='settled'"
        )
        params: list = []
        if room_name:
            sql += " AND room_name=?"
            params.append(room_name)
        if date_from:
            sql += " AND COALESCE(ended_at, started_at)>=?"
            params.append(date_from)
        if date_to:
            end = date_to + " 23:59:59" if len(date_to) == 10 else date_to
            sql += " AND COALESCE(ended_at, started_at)<=?"
            params.append(end)
        sql += " ORDER BY id DESC"
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]

    def player_daily_summary(
        self, room_name: str = "", date_str: str = "", nickname: str = ""
    ) -> List[Dict[str, Any]]:
        """
        玩家个人每日汇总：有效下注、有效局数、无效局数、当日输赢。
        date_str: YYYY-MM-DD，空则当天。
        """
        day = date_str or datetime.now().strftime("%Y-%m-%d")
        day_start = f"{day} 00:00:00"
        day_end = f"{day} 23:59:59"
        with self._conn() as conn:
            # 当日有下注的玩家
            bet_sql = (
                "SELECT b.nickname, b.round_id, b.amount, b.is_valid, b.invalid_reason, "
                "r.room_name, r.status "
                "FROM bets b JOIN rounds r ON r.id=b.round_id "
                "WHERE b.updated_at>=? AND b.updated_at<=?"
            )
            params: list = [day_start, day_end]
            if room_name:
                bet_sql += " AND r.room_name=?"
                params.append(room_name)
            if nickname:
                bet_sql += " AND b.nickname=?"
                params.append(nickname)
            bets = [dict(r) for r in conn.execute(bet_sql, tuple(params)).fetchall()]

            led_sql = (
                "SELECT nickname, change_amount, type, room_name FROM ledger "
                "WHERE created_at>=? AND created_at<=? AND type='对局输赢'"
            )
            led_params: list = [day_start, day_end]
            if room_name:
                led_sql += " AND room_name=?"
                led_params.append(room_name)
            if nickname:
                led_sql += " AND nickname=?"
                led_params.append(nickname)
            ledgers = [
                dict(r) for r in conn.execute(led_sql, tuple(led_params)).fetchall()
            ]

        summary: Dict[str, Dict[str, Any]] = {}
        for b in bets:
            nick = b["nickname"]
            key = nick
            if key not in summary:
                summary[key] = {
                    "date": day,
                    "nickname": nick,
                    "room_name": b.get("room_name") or room_name,
                    "valid_bet_amount": 0.0,
                    "valid_rounds": set(),
                    "invalid_rounds": set(),
                    "win_loss": 0.0,
                }
            item = summary[key]
            rid = b["round_id"]
            if b.get("is_valid"):
                item["valid_bet_amount"] += float(b.get("amount") or 0)
                item["valid_rounds"].add(rid)
            else:
                item["invalid_rounds"].add(rid)

        for led in ledgers:
            nick = led["nickname"]
            if nick not in summary:
                summary[nick] = {
                    "date": day,
                    "nickname": nick,
                    "room_name": led.get("room_name") or room_name,
                    "valid_bet_amount": 0.0,
                    "valid_rounds": set(),
                    "invalid_rounds": set(),
                    "win_loss": 0.0,
                }
            summary[nick]["win_loss"] += float(led.get("change_amount") or 0)

        out = []
        for item in summary.values():
            out.append(
                {
                    "date": item["date"],
                    "nickname": item["nickname"],
                    "room_name": item["room_name"],
                    "valid_bet_amount": round(item["valid_bet_amount"], 2),
                    "valid_round_count": len(item["valid_rounds"]),
                    "invalid_round_count": len(
                        item["invalid_rounds"] - item["valid_rounds"]
                    ),
                    "win_loss": round(item["win_loss"], 2),
                }
            )
        out.sort(key=lambda x: x["nickname"])
        return out

    # ---------- settings ----------

    DEFAULT_DIGIT_WEIGHT_ORDER = "0123456789"

    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=? LIMIT 1", (key,)
            ).fetchone()
            return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (key, value, _now()),
            )

    def get_digit_weight_order(self) -> str:
        """
        同点时数字组合比较顺序：字符串左侧数字更强。
        默认 0123456789 表示 0>1>2>...>9。
        """
        raw = (self.get_setting("digit_weight_order", self.DEFAULT_DIGIT_WEIGHT_ORDER) or "").strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        # 补齐缺失数字，保持已配置相对顺序
        for d in self.DEFAULT_DIGIT_WEIGHT_ORDER:
            if d not in digits:
                digits += d
        return digits[:10]

    def set_digit_weight_order(self, order: str) -> str:
        cleaned = "".join(ch for ch in (order or "") if ch.isdigit())
        # 去重保序
        seen = set()
        uniq = []
        for ch in cleaned:
            if ch not in seen:
                seen.add(ch)
                uniq.append(ch)
        for d in self.DEFAULT_DIGIT_WEIGHT_ORDER:
            if d not in seen:
                uniq.append(d)
        value = "".join(uniq[:10])
        self.set_setting("digit_weight_order", value)
        return value

    # ---------- 管理群（增删改查） ----------

    def list_game_rooms(self) -> List[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name FROM game_rooms ORDER BY name COLLATE NOCASE"
            ).fetchall()
            return [str(r["name"]) for r in rows]

    def add_game_room(self, name: str) -> str:
        name = (name or "").strip()
        if not name:
            raise ValueError("群名称不能为空")
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO game_rooms(name, created_at, updated_at) VALUES(?,?,?)",
                (name, now, now),
            )
            conn.execute(
                "UPDATE game_rooms SET updated_at=? WHERE name=?",
                (now, name),
            )
        return name

    def rename_game_room(self, old_name: str, new_name: str) -> str:
        old_name = (old_name or "").strip()
        new_name = (new_name or "").strip()
        if not old_name or not new_name:
            raise ValueError("群名称不能为空")
        if old_name == new_name:
            return new_name
        with self._conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM game_rooms WHERE name=? LIMIT 1", (old_name,)
            ).fetchone()
            if not exists:
                raise ValueError(f"群不存在: {old_name}")
            conflict = conn.execute(
                "SELECT 1 FROM game_rooms WHERE name=? LIMIT 1", (new_name,)
            ).fetchone()
            if conflict:
                raise ValueError(f"群已存在: {new_name}")
            conn.execute(
                "UPDATE game_rooms SET name=?, updated_at=? WHERE name=?",
                (new_name, _now(), old_name),
            )
            conn.execute(
                "UPDATE players SET room_name=? WHERE room_name=?",
                (new_name, old_name),
            )
            conn.execute(
                "UPDATE rounds SET room_name=? WHERE room_name=?",
                (new_name, old_name),
            )
            conn.execute(
                "UPDATE ledger SET room_name=? WHERE room_name=?",
                (new_name, old_name),
            )
        return new_name

    def delete_game_room(self, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM game_rooms WHERE name=?", (name,))
            return cur.rowcount > 0

    def ensure_game_room(self, name: str) -> str:
        """若不存在则加入管理列表。"""
        return self.add_game_room(name)
