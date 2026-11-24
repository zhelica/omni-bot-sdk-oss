"""
游戏消息收集插件。

开始表情 MD5 → 开启下注采集；
结束表情 MD5 → 答题截止（本局仍可收超时注，默认无效「答题时间超时」）；
该群收到红包消息 → 停止再收集本局下注。
仅数字下注有效，最低金额可配；同一用户以第一次有效数字为准；
后续非撤注词的文字/数字不覆盖；发「无效/取消/不压」才撤注。
支持多群（GUI 管理群列表）。实时写入本地 SQLite。
启动时打开余额/结算 GUI。
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from omni_bot_sdk.game.gui import start_game_gui
from omni_bot_sdk.game.store import GameStore
from omni_bot_sdk.plugins.interface import Plugin, PluginExcuteContext
from omni_bot_sdk.weixin.message_classes import EmojiMessage, Message, MessageType, TextMessage

if TYPE_CHECKING:
    from omni_bot_sdk.bot import Bot


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


class GameMessageCollectPluginConfig(BaseModel):
    """游戏消息收集插件配置。"""

    enabled: bool = True
    priority: int = 1500
    room_name: str = ""  # 兼容旧配置：启动时写入管理群列表
    start_emoji_md5: str = "52949bf9d43e8135aed3b0e6e7fe18bb"
    end_emoji_md5: str = "023d7db8d4e25231d865af981328de76"
    output_dir: str = "game_records"
    db_path: str = "game_records/game.db"
    min_bet: float = 50
    # 下注金额大于余额时是否判无效
    reject_over_balance: bool = True
    # 启动时打开 GUI
    open_gui: bool = True
    save_format: str = "json"
    # 本局撤注关键词（精确匹配）
    cancel_keywords: List[str] = Field(
        default_factory=lambda: ["无效", "取消", "不压"]
    )
    collect_non_text: bool = False
    skip_system: bool = True


class GameMessageCollectPlugin(Plugin):
    """监听指定群：开局/截止表情采集下注；红包消息后停止收集。"""

    priority = 1500
    name = "game-message-collect-plugin"

    def __init__(self, bot: "Bot" = None):
        super().__init__(bot)
        self.priority = getattr(self.plugin_config, "priority", self.__class__.priority)
        self._lock = threading.Lock()
        # 按群维护采集会话：
        # collecting / answer_closed(结束表情后) / round_id / messages
        self._sessions: Dict[str, Dict[str, Any]] = {}

        db_path = getattr(self.plugin_config, "db_path", "game_records/game.db")
        path = Path(db_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        self.store = GameStore(path)

        # 兼容旧配置：把 config.room_name 写入管理群
        cfg_room = (getattr(self.plugin_config, "room_name", "") or "").strip()
        if cfg_room:
            try:
                self.store.ensure_game_room(cfg_room)
            except Exception as e:
                self.logger.warning(f"写入默认管理群失败: {e}")

        if getattr(self.plugin_config, "open_gui", True):
            try:
                ocr = getattr(self.bot, "ocr_processor", None)
                start_game_gui(
                    store=self.store,
                    room_name=cfg_room,
                    ocr_processor=ocr,
                    report_dir=getattr(self.plugin_config, "output_dir", "game_records"),
                    min_bet=float(getattr(self.plugin_config, "min_bet", 50) or 50),
                    # 核对列表等发群图；结算图仍默认存桌面
                    send_file_callback=self._send_report_file,
                )
            except Exception as e:
                self.logger.error(f"启动游戏 GUI 失败: {e}", exc_info=True)

    def _send_report_file(self, file_path: str, room_name: str) -> None:
        """结算表生成后发群：优先发图片，xlsx 兜底发文件。"""
        from omni_bot_sdk.rpa.action_handlers import SendFileAction, SendImageAction

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"结算文件不存在: {file_path}")
        target = (room_name or "").strip()
        if not target:
            raise ValueError("群名称为空，无法发送结算表")

        suffix = path.suffix.lower()
        if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
            action = SendImageAction(
                image_path=str(path.resolve()),
                target=target,
                is_chatroom=True,
            )
        else:
            action = SendFileAction(
                file_path=str(path.resolve()),
                target=target,
                is_chatroom=True,
            )
        try:
            if getattr(self.bot, "processor_service", None):
                self.bot.processor_service.add_rpa_actions([action])
            else:
                self.bot.rpa_task_queue.put(action)
        except Exception:
            self.bot.rpa_task_queue.put(action)
        self.logger.info(f"结算表已提交发群: room={target}, file={path}")

    def get_priority(self) -> int:
        return self.priority

    def get_plugin_name(self) -> str:
        return self.name

    def get_plugin_description(self) -> str:
        return "表情开局/收局采集数字下注，本地余额持久化，GUI 结算"

    @classmethod
    def get_plugin_config_schema(cls):
        return GameMessageCollectPluginConfig

    def _normalize_md5(self, value: Any) -> str:
        md5 = str(value or "").strip().lower()
        # parser_emoji 失败时可能返回数字 0
        if md5 in {"", "0", "none", "null"}:
            return ""
        return md5

    # 本机表情 MD5 重读暂关闭（改用手机发送）
    # def _parse_emoji_md5_from_content(self, content: Any) -> str: ...
    # async def _resolve_emoji_md5(self, message: Message) -> str: ...

    def _room_nickname(self, message: Message) -> str:
        room = message.room
        if not room:
            return ""
        return _safe_str(getattr(room, "display_name", "") or getattr(room, "nick_name", ""))

    @staticmethod
    def _member_name_parts(member: Any) -> Dict[str, str]:
        """拆出备注 / 群昵称 / 微信昵称，便于日志与红包比对。"""
        if member is None:
            return {"remark": "", "room_remark": "", "nick_name": ""}
        return {
            "remark": _safe_str(getattr(member, "remark", "") or ""),
            "room_remark": _safe_str(getattr(member, "room_remark", "") or ""),
            "nick_name": _safe_str(getattr(member, "nick_name", "") or ""),
        }

    @classmethod
    def _group_member_name(cls, member: Any) -> str:
        """
        红包比对名：只取个人备注。
        无备注则返回空（下注判无效，不做微信昵称/群昵称兜底）。
        """
        if member is None:
            return ""
        return cls._member_name_parts(member)["remark"]

    @classmethod
    def _display_fallback_name(cls, member: Any, *extra: str) -> str:
        """仅用于日志/无效单展示，不参与红包比对。"""
        parts = cls._member_name_parts(member) if member is not None else {
            "remark": "",
            "room_remark": "",
            "nick_name": "",
        }
        for name in (
            parts["remark"],
            parts["room_remark"],
            parts["nick_name"],
            *[_safe_str(x) for x in extra],
            _safe_str(getattr(member, "username", "") or "") if member is not None else "",
        ):
            if name:
                return name
        return ""

    def _find_room_member(
        self, room_username: str, *, wxid: str = "", name: str = ""
    ) -> Optional[Any]:
        """按 wxid 或群昵称/昵称在群成员列表中查找。"""
        if not room_username or (not wxid and not name):
            return None
        try:
            members = self.bot.db.get_room_member_list(room_username) or []
        except Exception as e:
            self.logger.warning(f"get_room_member_list 失败: {e}")
            return None
        name_key = (name or "").strip()
        for member in members:
            if wxid and _safe_str(getattr(member, "username", "")) == wxid:
                return member
            if name_key:
                candidates = {
                    self._group_member_name(member),
                    _safe_str(getattr(member, "room_remark", "")),
                    _safe_str(getattr(member, "nick_name", "")),
                    _safe_str(getattr(member, "remark", "")),
                    _safe_str(getattr(member, "display_name", "")),
                }
                if name_key in candidates:
                    return member
        return None

    def _managed_rooms(self) -> List[str]:
        rooms = self.store.list_game_rooms()
        if rooms:
            return rooms
        # 兜底：尚无 GUI 维护时用配置里的单群
        cfg = (getattr(self.plugin_config, "room_name", "") or "").strip()
        return [cfg] if cfg else []

    def _is_target_room(self, message: Message) -> bool:
        rooms = self._managed_rooms()
        if not rooms:
            self.logger.warning("未配置/未维护任何管理群，跳过消息")
            return False
        current = self._room_nickname(message)
        return bool(current) and current in rooms

    def _cancel_keywords(self) -> set:
        raw = getattr(self.plugin_config, "cancel_keywords", None) or [
            "无效",
            "取消",
            "不压",
        ]
        return {str(x).strip() for x in raw if str(x).strip()}

    def _is_cancel_text(self, content: str) -> bool:
        return _safe_str(content) in self._cancel_keywords()

    def _is_person_wxid(self, username: str) -> bool:
        u = _safe_str(username)
        if not u:
            return False
        # 群ID不能当发送者
        if u.endswith("@chatroom"):
            return False
        return True

    def _self_identity(self) -> Tuple[str, str]:
        user = getattr(self.bot, "user_info", None)
        wxid = _safe_str(getattr(user, "account", "") if user else "")
        nick = _safe_str(
            (getattr(user, "nickname", "") if user else "")
            or (getattr(user, "alias", "") if user else "")
            or wxid
        )
        return nick, wxid

    def _username_from_name2id(
        self, sender_id: Any, message_db_path: Any
    ) -> str:
        """
        直接查消息库 Name2Id(rowid→user_name)。
        不用 get_contact_by_sender_id：该接口会错查到无关联系人/群ID。
        例：自己发言 real_sender_id=2 → wxid_xxx；他人 3372 → jun90hou。
        """
        if not isinstance(sender_id, int) or not sender_id or not message_db_path:
            return ""
        try:
            rows = self.bot.db.execute_query(
                Path(message_db_path),
                "SELECT user_name FROM Name2Id WHERE rowid=?",
                (sender_id,),
            )
            if rows:
                return _safe_str(rows[0][0])
        except Exception as e:
            self.logger.warning(
                f"Name2Id 查询失败: sender_id={sender_id} err={e}"
            )
        return ""

    # 群消息常见前缀：wxid_xxx: / xxx@openim: / 自定义微信号 jun90hou:
    _SENDER_PREFIX_RE = re.compile(
        r"^([A-Za-z][\w.-]{1,63}|wxid_\w+|[^:\s\n]+@openim)\s*:\s*(?:\r?\n)?([\s\S]*)$"
    )

    def _probe_sender_prefix_from_text(self, *probes: Any) -> Optional[str]:
        """从消息原文解析发送者前缀（微信号/wxid），不含群ID。"""
        for probe in probes:
            text = probe if isinstance(probe, str) else _safe_str(probe)
            if not text:
                continue
            # 优先整段匹配「前缀:\\n正文」
            match = self._SENDER_PREFIX_RE.match(text.strip())
            if match:
                prefix = match.group(1).strip()
                if prefix.endswith("@chatroom"):
                    continue
                return prefix
            first_line = text.split("\n", 1)[0].strip()
            match = re.match(
                r"^([A-Za-z][\w.-]{1,63}|wxid_\w+|[^:\s]+@openim)\s*:?\s*$",
                first_line,
            )
            if match:
                prefix = match.group(1).strip()
                if not prefix.endswith("@chatroom"):
                    return prefix
        return None

    def _strip_sender_prefix(self, text: str, sender_wxid: str = "") -> str:
        raw = text if isinstance(text, str) else _safe_str(text)
        if not raw:
            return ""
        if sender_wxid and raw.startswith(sender_wxid):
            raw = raw[len(sender_wxid) :]
            if raw.startswith(":"):
                raw = raw[1:]
            return raw.lstrip("\u2005").lstrip("\r\n").strip()
        match = self._SENDER_PREFIX_RE.match(raw.strip())
        if match:
            return match.group(2).lstrip("\u2005").strip()
        return raw.strip()

    def _enrich_from_room_member(
        self, room_username: str, sender_wxid: str, contact_nickname: str
    ) -> Tuple[str, str, Dict[str, str], Any]:
        """
        用群成员列表补全展示名；必要时用名字反查 wxid。
        返回 (primary_name, wxid, name_parts, member|None)。
        """
        empty_parts = {"remark": "", "room_remark": "", "nick_name": ""}
        if not room_username:
            return contact_nickname, sender_wxid, empty_parts, None
        member = None
        if sender_wxid:
            member = self._find_room_member(room_username, wxid=sender_wxid)
        if member is None and contact_nickname and not sender_wxid:
            member = self._find_room_member(room_username, name=contact_nickname)
        if member is None:
            return contact_nickname, sender_wxid, empty_parts, None
        parts = self._member_name_parts(member)
        # 红包比对名只取备注，无备注保持空（不回退微信名）
        primary = self._group_member_name(member)
        wxid = sender_wxid or _safe_str(getattr(member, "username", ""))
        return primary, wxid, parts, member

    def _format_name_parts_log(self, parts: Dict[str, str], primary: str = "") -> str:
        remark = parts.get("remark") or "-"
        room_remark = parts.get("room_remark") or "-"
        nick_name = parts.get("nick_name") or "-"
        claim = (primary or parts.get("remark") or "-") or "-"
        return (
            f"备注={remark} 群昵称={room_remark} 微信昵称={nick_name} "
            f"红包比对名={claim}"
        )

    def _resolve_contact_nickname(
        self, message: Message
    ) -> Tuple[str, str, Dict[str, str]]:
        """
        解析 (红包比对名=备注, wxid, 名称部件)。
        红包比对只用备注；无备注返回空字符串，下注侧判无效。
        查发送者：内容前缀微信号 → Name2Id → 群成员列表。
        """
        empty_parts = {"remark": "", "room_remark": "", "nick_name": ""}
        content_probe = getattr(message, "content", None)
        parsed_probe = getattr(message, "parsed_content", None)
        # 原始 message_content 也要试（content 字段可能已被处理）
        raw_probe = getattr(message, "message_content", None)
        if isinstance(raw_probe, bytes):
            raw_probe = None
        content_prefix = self._probe_sender_prefix_from_text(
            content_probe, parsed_probe, raw_probe
        )

        room_username = ""
        if message.room:
            room_username = _safe_str(getattr(message.room, "username", ""))

        contact_nickname = ""
        sender_wxid = ""
        parts = dict(empty_parts)
        member: Any = None

        # 1) 内容前缀：jun90hou: / wxid_xxx: / 偶发群昵称:
        #    先当微信号查，查不到再按备注/群昵称/微信昵称在群成员里反查
        if content_prefix and self._is_person_wxid(content_prefix):
            try:
                contact = self.bot.db.get_contact_by_username(content_prefix)
            except Exception as e:
                self.logger.warning(
                    f"get_contact_by_username({content_prefix}) 失败: {e}"
                )
                contact = None
            if contact and self._is_person_wxid(
                _safe_str(getattr(contact, "username", ""))
            ):
                sender_wxid = _safe_str(getattr(contact, "username", ""))
                contact_nickname = self._group_member_name(contact)
                parts = self._member_name_parts(contact)
                member = contact
            else:
                member = self._find_room_member(room_username, name=content_prefix)
                if member:
                    sender_wxid = _safe_str(getattr(member, "username", ""))
                    contact_nickname = self._group_member_name(member)
                    parts = self._member_name_parts(member)
                elif re.match(r"^(wxid_\w+|[\w.-]+@openim|[A-Za-z][\w.-]{1,63})$", content_prefix):
                    # 保留为微信号，稍后靠群成员补全
                    sender_wxid = content_prefix
                    contact_nickname = ""
                else:
                    sender_wxid = ""
                    contact_nickname = content_prefix

            contact_nickname, sender_wxid, enrich_parts, enrich_member = (
                self._enrich_from_room_member(
                    room_username, sender_wxid, contact_nickname
                )
            )
            if enrich_member is not None:
                member = enrich_member
                parts = enrich_parts
            elif enrich_parts.get("remark") or enrich_parts.get("room_remark") or enrich_parts.get("nick_name"):
                parts = enrich_parts
            if contact_nickname or sender_wxid:
                primary = contact_nickname or sender_wxid or content_prefix
                self.logger.info(
                    f"发送者来自内容前缀: prefix={content_prefix} wxid={sender_wxid} "
                    f"{self._format_name_parts_log(parts, primary)}"
                )
                return primary, sender_wxid, parts

        # 2) 无内容前缀时：用消息库 Name2Id(rowid) 拿真正 username
        #    （自己发言常无前缀，real_sender_id=2 → 自己的 wxid）
        sender_id: Any = message.real_sender_id
        db_path = getattr(message, "message_db_path", None)
        name2id_user = self._username_from_name2id(sender_id, db_path)

        if name2id_user and self._is_person_wxid(name2id_user):
            sender_wxid = name2id_user
            try:
                contact = self.bot.db.get_contact_by_username(sender_wxid)
            except Exception as e:
                self.logger.warning(f"get_contact_by_username({sender_wxid}) 失败: {e}")
                contact = None
            if contact:
                contact_nickname = self._group_member_name(contact)
                parts = self._member_name_parts(contact)
                member = contact
            contact_nickname, sender_wxid, enrich_parts, enrich_member = (
                self._enrich_from_room_member(
                    room_username, sender_wxid, contact_nickname
                )
            )
            if enrich_member is not None:
                member = enrich_member
                parts = enrich_parts
            elif enrich_parts.get("remark") or enrich_parts.get("room_remark") or enrich_parts.get("nick_name"):
                parts = enrich_parts
            # 自己：展示名再补一次
            self_wxid = self._self_identity()[1]
            if sender_wxid == self_wxid and not contact_nickname:
                contact_nickname = self._self_identity()[0]
                if not parts.get("nick_name"):
                    parts["nick_name"] = contact_nickname
            if contact_nickname or sender_wxid:
                primary = contact_nickname or sender_wxid
                self.logger.info(
                    f"发送者来自 Name2Id: id={sender_id} wxid={sender_wxid} "
                    f"{self._format_name_parts_log(parts, primary)}"
                )
                return primary, sender_wxid, parts

        # 3) is_self（contact 可能被工厂设错成群，仅作兜底）
        if getattr(message, "is_self", False) and not content_prefix:
            nick, wxid = self._self_identity()
            nick, wxid, parts, _ = self._enrich_from_room_member(
                room_username, wxid, nick
            )
            if not parts.get("nick_name"):
                parts["nick_name"] = nick
            return nick or wxid, wxid, parts

        if not contact_nickname and not sender_wxid:
            self.logger.warning(
                f"无法解析发送者: real_sender_id={message.real_sender_id} "
                f"name2id={name2id_user or '-'} content_prefix={content_prefix} "
                f"content={_safe_str(content_probe)[:80]}"
            )
            return "未知用户", "", empty_parts

        return contact_nickname, sender_wxid or "", parts

    def _extract_content(self, message: Message, sender_wxid: str = "") -> Optional[str]:
        if isinstance(message, TextMessage) or message.local_type in (
            MessageType.Text,
            MessageType.Text2,
        ):
            # 优先用未剥离的原文，保证能去掉 jun90hou: 这类前缀
            raw = getattr(message, "message_content", None)
            if raw is None or isinstance(raw, bytes):
                raw = getattr(message, "content", None)
            if raw is None:
                raw = message.parsed_content
            return self._strip_sender_prefix(_safe_str(raw), sender_wxid)

        if not getattr(self.plugin_config, "collect_non_text", False):
            return None
        if isinstance(message, EmojiMessage):
            return None
        try:
            text = message.to_text()
            if text:
                return self._strip_sender_prefix(_safe_str(text), sender_wxid)
        except Exception:
            pass
        return None

    def _parse_bet_amount(self, content: str) -> Tuple[Optional[float], str]:
        """解析下注。返回 (amount|None, reason)。"""
        text = _safe_str(content)
        if not text:
            return None, "空内容"
        if self._is_cancel_text(text):
            return None, "玩家主动无效"
        # 纯数字（允许整数）
        if not re.fullmatch(r"\d+(\.\d+)?", text):
            return None, "非数字无效"
        amount = float(text)
        min_bet = float(getattr(self.plugin_config, "min_bet", 50) or 50)
        if amount < min_bet:
            return None, f"下注金额低于最低 {min_bet:g} 限制"
        return amount, ""

    def _start_game(self, room_name: str) -> None:
        with self._lock:
            # 上一局若还在等红包截止，开新局前先清掉
            self._sessions.pop(room_name, None)
            rnd = self.store.start_round(room_name)
            self._sessions[room_name] = {
                "collecting": True,
                "answer_closed": False,
                "started_at": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "round_id": int(rnd["id"]),
                "messages": [],
            }
        self.logger.info(f"游戏开始 round=#{rnd['id']} room={room_name}")

    def _end_game_and_save(self, room_name: str) -> None:
        """结束表情：答题截止并落库 ended；会话保留，继续收超时注直到红包。"""
        with self._lock:
            sess = self._sessions.get(room_name)
            if not sess or not sess.get("collecting"):
                return
            if sess.get("answer_closed"):
                self.logger.info(
                    f"本局已答题截止，忽略重复结束表情: room={room_name}"
                )
                return
            sess["answer_closed"] = True
            round_id = sess.get("round_id")
            records = list(sess.get("messages") or [])
            started_at = sess.get("started_at") or datetime.now().strftime(
                "%Y%m%d_%H%M%S"
            )

        self.store.end_round(room_name)
        self._save_json_snapshot(room_name, started_at, records, round_id)
        self.logger.info(
            f"答题截止 round=#{round_id} room={room_name} 原始消息={len(records)}；"
            f"超时下注仍统计(默认无效)，收到红包后停止收集"
        )

    def _stop_collect_on_red_packet(self, room_name: str) -> None:
        """该群红包消息：本局下注收集正式结束。"""
        with self._lock:
            sess = self._sessions.pop(room_name, None)
        if not sess:
            return
        round_id = sess.get("round_id")
        records = list(sess.get("messages") or [])
        started_at = sess.get("started_at") or datetime.now().strftime("%Y%m%d_%H%M%S")
        # 若结束表情未到、先发了红包，也尽量把局标为 ended，便于 GUI 核对
        try:
            rnd = self.store.get_round(int(round_id)) if round_id is not None else None
        except Exception:
            rnd = None
        if rnd and str(rnd.get("status") or "") == "collecting":
            self.store.end_round(room_name)
        try:
            self._save_json_snapshot(room_name, started_at, records, round_id)
        except Exception:
            self.logger.exception("红包截止时保存快照失败")
        self.logger.info(
            f"收到红包，停止本局下注收集 round=#{round_id} room={room_name} "
            f"原始消息={len(records)}"
        )

    def _session_collecting(self, room_name: str) -> bool:
        """是否仍接受本局下注（含结束表情后的超时注；红包后为 False）。"""
        sess = self._sessions.get(room_name)
        if not sess or not sess.get("collecting"):
            return False
        rid = sess.get("round_id")
        if rid is not None:
            try:
                rnd = self.store.get_round(int(rid))
            except Exception:
                rnd = None
            # 已结算/作废则清会话；ended 仍可收超时注
            status = str((rnd or {}).get("status") or "")
            if not rnd or status in ("settled", "voided"):
                self._sessions.pop(room_name, None)
                return False
        return True

    def _session_answer_closed(self, room_name: str) -> bool:
        sess = self._sessions.get(room_name)
        return bool(sess and sess.get("answer_closed"))

    def _session_round_id(self, room_name: str) -> Optional[int]:
        sess = self._sessions.get(room_name)
        if not sess:
            return None
        rid = sess.get("round_id")
        return int(rid) if rid is not None else None

    def _resolve_output_dir(self) -> Path:
        raw = (getattr(self.plugin_config, "output_dir", "") or "game_records").strip()
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _safe_filename(self, name: str) -> str:
        keep = []
        for ch in name:
            if ch.isalnum() or ch in ("-", "_", "."):
                keep.append(ch)
            elif ch.isspace():
                keep.append("_")
            else:
                keep.append("_")
        return "".join(keep).strip("_") or "room"

    def _save_json_snapshot(
        self,
        room_name: str,
        started_at: str,
        records: List[Dict[str, Any]],
        round_id: Optional[int],
    ) -> Path:
        output_dir = self._resolve_output_dir()
        ended_at = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"{self._safe_filename(room_name)}_{started_at}_{ended_at}"
        bets = self.store.list_bets(round_id, valid_only=False) if round_id else []
        payload = {
            "round_id": round_id,
            "room_name": room_name,
            "started_at": started_at,
            "ended_at": ended_at,
            "raw_message_count": len(records),
            "bets": bets,
            "messages": records,
        }
        path = output_dir / f"{stem}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    def _find_maintained_player(
        self,
        room_name: str,
        nickname: str,
        wxid: str,
        name_parts: Optional[Dict[str, str]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        按备注/群昵称/微信昵称/wxid 查找 GUI 已维护用户。
        返回 (player, 账户昵称)；账户昵称优先用库内昵称，保证余额账户一致。
        """
        candidates: List[str] = []
        parts = name_parts or {}
        for key in ("remark", "room_remark", "nick_name"):
            val = _safe_str(parts.get(key) or "")
            if val and val not in candidates:
                candidates.append(val)
        if nickname and nickname not in candidates:
            candidates.append(nickname)

        for name in candidates:
            player = self.store.get_player(name, room_name)
            if player:
                return player, _safe_str(player.get("nickname") or name)

        # 备注 #001#洋洋 与账户 #001#chat：按两 # 间编号关联（兼容旧 001#xxx）
        from omni_bot_sdk.game.settlement import _remark_match_key

        for name in candidates:
            key = _remark_match_key(name)
            if not key:
                continue
            for p in self.store.list_players(room_name):
                if _remark_match_key(p.get("nickname") or "") == key:
                    return p, _safe_str(p.get("nickname") or name)

        if wxid:
            for p in self.store.list_players(room_name):
                if _safe_str(p.get("wxid")) == _safe_str(wxid):
                    return p, _safe_str(p.get("nickname") or nickname)
        return None, nickname

    def _record_bet(
        self,
        room_name: str,
        nickname: str,
        wxid: str,
        content: str,
        message: Message,
        name_parts: Optional[Dict[str, str]] = None,
    ) -> None:
        round_id = self._session_round_id(room_name)
        if not round_id:
            return

        # 红包比对只用备注；无备注直接无效（不做群昵称/微信昵称兜底）
        parts = name_parts or {}
        remark = _safe_str(parts.get("remark") or "")
        claim_name = remark
        display_name = (
            remark
            or _safe_str(parts.get("room_remark") or "")
            or _safe_str(parts.get("nick_name") or "")
            or _safe_str(nickname)
            or _safe_str(wxid)
            or "unknown"
        )
        player, account_nick = self._find_maintained_player(
            room_name, display_name, wxid, name_parts
        )
        # 落库昵称：有备注用备注；无备注用展示名（仅记无效单）
        nickname = claim_name or display_name

        prev = self.store.get_bet(round_id, nickname) if nickname else None

        def _append_msg(
            *,
            amount: float,
            is_valid: bool,
            invalid_reason: str,
        ) -> None:
            with self._lock:
                sess = self._sessions.get(room_name)
                if not sess:
                    return
                msgs = sess.setdefault("messages", [])
                msgs.append(
                    {
                        "nickname": nickname,
                        "account_nick": account_nick,
                        "remark": parts.get("remark") or "",
                        "room_remark": parts.get("room_remark") or "",
                        "nick_name": parts.get("nick_name") or "",
                        "content": content,
                        "room_name": room_name,
                        "sender_wxid": wxid,
                        "amount": amount,
                        "is_valid": is_valid,
                        "invalid_reason": invalid_reason,
                        "server_id": message.server_id,
                        "str_time": message.str_time,
                    }
                )

        if not claim_name:
            amount, _reason = self._parse_bet_amount(content)
            reason = "无备注，无法与红包比对"
            self.store.upsert_bet(
                round_id=round_id,
                nickname=nickname,
                amount=float(amount or 0),
                wxid=wxid,
                content=content,
                is_valid=False,
                invalid_reason=reason,
            )
            _append_msg(
                amount=float(amount or 0),
                is_valid=False,
                invalid_reason=reason,
            )
            self.logger.info(
                f"下注无效: room={room_name} 展示名={display_name} wxid={wxid or '-'} "
                f"原因={reason} content={content}"
            )
            return

        if not player:
            amount, reason = self._parse_bet_amount(content)
            self.store.upsert_bet(
                round_id=round_id,
                nickname=nickname,
                amount=float(amount or 0),
                wxid=wxid,
                content=content,
                is_valid=False,
                invalid_reason="下注无效余额为零 请上分",
            )
            _append_msg(
                amount=float(amount or 0),
                is_valid=False,
                invalid_reason="下注无效余额为零 请上分",
            )
            return

        # 主动撤注：无效 / 取消 / 不压
        if self._is_cancel_text(content):
            bet_amount = float(prev.get("amount") or 0) if prev else 0
            reason = f"玩家主动无效({_safe_str(content)})"
            self.store.upsert_bet(
                round_id=round_id,
                nickname=nickname,
                amount=bet_amount,
                wxid=wxid,
                content=content,
                is_valid=False,
                invalid_reason=reason,
            )
            _append_msg(amount=bet_amount, is_valid=False, invalid_reason=reason)
            return

        # 已有有效数字下注：后续文字/再发数字一律忽略，保留第一次
        if prev and int(prev.get("is_valid") or 0) == 1:
            self.logger.info(
                f"已有有效下注 amount={prev.get('amount')}，忽略后续消息: {content}"
            )
            _append_msg(
                amount=float(prev.get("amount") or 0),
                is_valid=True,
                invalid_reason="已保留首次下注，忽略后续",
            )
            return

        amount, reason = self._parse_bet_amount(content)
        # 非数字且尚无有效下注：忽略，不写成无效（仍可再发数字）
        if amount is None and reason == "非数字无效":
            self.logger.info(f"非数字消息忽略（未撤注）: nick={nickname} content={content}")
            _append_msg(amount=0, is_valid=False, invalid_reason="非数字忽略")
            return

        if amount is None:
            # 低于最低等：记无效
            self.store.upsert_bet(
                round_id=round_id,
                nickname=nickname,
                amount=0,
                wxid=wxid,
                content=content,
                is_valid=False,
                invalid_reason=reason,
            )
            _append_msg(amount=0, is_valid=False, invalid_reason=reason)
            return

        bet_amount = float(amount)
        if getattr(self.plugin_config, "reject_over_balance", True):
            bal = float(player.get("balance") or 0)
            if bet_amount > bal:
                reason = f"下注金额大于玩家当前账户积分(余额{bal:g})"
                self.store.upsert_bet(
                    round_id=round_id,
                    nickname=nickname,
                    amount=bet_amount,
                    wxid=wxid,
                    content=content,
                    is_valid=False,
                    invalid_reason=reason,
                )
                _append_msg(
                    amount=bet_amount, is_valid=False, invalid_reason=reason
                )
                return

        if wxid and not player.get("wxid"):
            self.store.ensure_player(
                account_nick or nickname,
                room_name,
                wxid,
                float(player.get("balance") or 0),
            )

        # 结束表情之后：仍统计进本局，默认无效，可在 GUI 手动改有效
        if self._session_answer_closed(room_name):
            reason = "答题时间超时"
            self.store.upsert_bet(
                round_id=round_id,
                nickname=nickname,
                amount=bet_amount,
                wxid=wxid,
                content=content,
                is_valid=False,
                invalid_reason=reason,
            )
            _append_msg(amount=bet_amount, is_valid=False, invalid_reason=reason)
            self.logger.info(
                f"超时下注: room={room_name} 备注={nickname} 账户={account_nick or '-'} "
                f"content={content} amount={bet_amount} reason={reason}"
            )
            return

        self.store.upsert_bet(
            round_id=round_id,
            nickname=nickname,
            amount=bet_amount,
            wxid=wxid,
            content=content,
            is_valid=True,
            invalid_reason="",
        )
        _append_msg(amount=bet_amount, is_valid=True, invalid_reason="")
        self.logger.info(
            f"下注: room={room_name} 备注={nickname} 账户={account_nick or '-'} "
            f"content={content} valid=True amount={bet_amount}"
        )

    async def handle_message(self, context: PluginExcuteContext) -> None:
        message = context.get_message()
        if not message.is_chatroom:
            return
        if not self._is_target_room(message):
            return

        room_name = self._room_nickname(message)
        start_md5 = self._normalize_md5(getattr(self.plugin_config, "start_emoji_md5", ""))
        end_md5 = self._normalize_md5(getattr(self.plugin_config, "end_emoji_md5", ""))

        if message.local_type == MessageType.Emoji:
            emoji_md5 = self._normalize_md5(getattr(message, "md5", ""))
            self.logger.info(
                f"收到表情包: room={room_name} md5={emoji_md5 or '(空)'} "
                f"start={start_md5 or '-'} end={end_md5 or '-'}"
            )
            if emoji_md5 and emoji_md5 == start_md5:
                self._start_game(room_name)
                return
            if emoji_md5 and emoji_md5 == end_md5:
                if self._session_collecting(room_name):
                    self._end_game_and_save(room_name)
                else:
                    self.logger.info(f"收到结束表情，但当前未在收集中: room={room_name}")
                return
            return

        # 以该群红包消息为截止：之后不再收集本局下注
        if message.local_type == MessageType.RedEnvelope:
            self.logger.info(f"收到红包消息: room={room_name}，停止本局下注收集")
            self._stop_collect_on_red_packet(room_name)
            return

        if getattr(self.plugin_config, "skip_system", True) and message.local_type in (
            MessageType.System,
            MessageType.Pat,
        ):
            return

        if message.local_type not in (MessageType.Text, MessageType.Text2):
            return

        nickname, sender_wxid, name_parts = self._resolve_contact_nickname(message)
        content = self._extract_content(message, sender_wxid=sender_wxid)
        if content is None:
            return

        self.logger.info(
            f"解析群消息: 群={room_name} wxid={sender_wxid or '-'} "
            f"{self._format_name_parts_log(name_parts, nickname)} 内容={content}"
        )

        if not self._session_collecting(room_name):
            return

        self._record_bet(
            room_name,
            nickname,
            sender_wxid,
            content,
            message,
            name_parts=name_parts,
        )
