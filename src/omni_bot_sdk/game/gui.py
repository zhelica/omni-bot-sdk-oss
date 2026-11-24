"""游戏后台 GUI：余额增删改查 + 上传截图结算。"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable, Dict, List, Optional

from omni_bot_sdk.game.claim_ocr import ClaimImageOCR
from omni_bot_sdk.game.settlement import SettlementEngine
from omni_bot_sdk.game.store import GameStore

logger = logging.getLogger(__name__)

# 界面色板：清爽灰底 + 青绿主色（避免老式灰窗体）
UI = {
    "bg": "#F4F6F8",
    "surface": "#FFFFFF",
    "surface_2": "#EEF2F6",
    "border": "#D7DEE7",
    "text": "#1B2430",
    "muted": "#667788",
    "primary": "#0F766E",
    "primary_hover": "#0D9488",
    "primary_fg": "#FFFFFF",
    "danger": "#B42318",
    "danger_bg": "#FEF3F2",
    "accent": "#0EA5E9",
    "row_odd": "#FFFFFF",
    "row_even": "#F0F7F6",
    "row_invalid": "#FEF3F2",
    "row_invalid_fg": "#912018",
    "select": "#CCFBF1",
    "header": "#0F766E",
    "header_fg": "#FFFFFF",
    "status_bg": "#E8EEF2",
    "font": ("Microsoft YaHei UI", 11),
    "font_sm": ("Microsoft YaHei UI", 10),
    "font_bold": ("Microsoft YaHei UI", 11, "bold"),
    "font_title": ("Microsoft YaHei UI", 16, "bold"),
    "font_subtitle": ("Microsoft YaHei UI", 10),
}


class GameAdminApp(tk.Tk):
    def __init__(
        self,
        store: GameStore,
        room_name: str = "",
        ocr_processor=None,
        report_dir: str = "game_records",
        min_bet: float = 50,
        send_file_callback: Optional[Callable[[str, str], None]] = None,
    ):
        super().__init__()
        self.store = store
        self.min_bet = min_bet
        self.send_file_callback = send_file_callback
        self.ocr = ClaimImageOCR(ocr_processor=ocr_processor)
        self.engine = SettlementEngine(store, report_dir=report_dir)
        # 初始化管理群列表；兼容旧配置里的单个 room_name
        if room_name and room_name.strip():
            try:
                self.store.ensure_game_room(room_name.strip())
            except Exception:
                pass
        rooms = self.store.list_game_rooms()
        self.room_name = (room_name or "").strip() or (rooms[0] if rooms else "")
        self.title(f"游戏后台 · {self.room_name or '未选择群'}")
        self.minsize(1200, 760)
        self.configure(bg=UI["bg"])
        # 先隐藏，等 UI 建完再用真实工作区贴右侧显示（避免默认落到左上角挡微信）
        self.withdraw()
        self._setup_styles()
        self._build_ui()
        self.refresh_all()
        self.after(10, self._show_on_screen_right)

    @staticmethod
    def _primary_work_area() -> tuple[int, int, int, int]:
        """返回主屏工作区 (left, top, width, height)，优先 Win32，避免 DPI 下 winfo 不准。"""
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            # SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                left, top = int(rect.left), int(rect.top)
                return left, top, int(rect.right - rect.left), int(rect.bottom - rect.top)
        except Exception:
            pass
        return 0, 0, 1920, 1080

    def _show_on_screen_right(self) -> None:
        """窗口贴主屏右侧显示，并短暂置顶，避免被微信挡住。"""
        win_w, win_h = 1400, 900
        left, top, work_w, work_h = self._primary_work_area()
        try:
            # 兜底：若 Win32 失败再用 Tk，并取较大值
            tw = int(self.winfo_screenwidth() or 0)
            th = int(self.winfo_screenheight() or 0)
            if tw > work_w:
                work_w = tw
            if th > work_h:
                work_h = th
        except Exception:
            pass

        win_w = min(win_w, max(900, work_w - 48))
        win_h = min(win_h, max(640, work_h - 48))
        x = left + max(0, work_w - win_w - 24)
        y = top + max(0, min(48, (work_h - win_h) // 10))
        self.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.deiconify()
        self.lift()
        try:
            self.attributes("-topmost", True)
            self.after(400, lambda: self.attributes("-topmost", False))
        except Exception:
            pass
        try:
            self.focus_force()
        except Exception:
            pass

    def _setup_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", font=UI["font"], foreground=UI["text"])
        style.configure("TFrame", background=UI["bg"])
        style.configure("Card.TFrame", background=UI["surface"])
        style.configure("Header.TFrame", background=UI["surface"])
        style.configure("Status.TFrame", background=UI["status_bg"])
        style.configure(
            "TLabel",
            background=UI["bg"],
            foreground=UI["text"],
            font=UI["font"],
        )
        style.configure(
            "Card.TLabel",
            background=UI["surface"],
            foreground=UI["text"],
            font=UI["font"],
        )
        style.configure(
            "Muted.TLabel",
            background=UI["bg"],
            foreground=UI["muted"],
            font=UI["font_sm"],
        )
        style.configure(
            "CardMuted.TLabel",
            background=UI["surface"],
            foreground=UI["muted"],
            font=UI["font_sm"],
        )
        style.configure(
            "Title.TLabel",
            background=UI["surface"],
            foreground=UI["text"],
            font=UI["font_title"],
        )
        style.configure(
            "Subtitle.TLabel",
            background=UI["surface"],
            foreground=UI["muted"],
            font=UI["font_subtitle"],
        )
        style.configure(
            "Status.TLabel",
            background=UI["status_bg"],
            foreground=UI["muted"],
            font=UI["font_sm"],
            padding=(12, 8),
        )
        style.configure(
            "Section.TLabel",
            background=UI["surface"],
            foreground=UI["text"],
            font=UI["font_bold"],
            padding=(0, 8, 0, 4),
        )

        style.configure(
            "TButton",
            font=UI["font"],
            padding=(12, 8),
            background=UI["surface_2"],
            foreground=UI["text"],
            borderwidth=0,
            focusthickness=0,
        )
        style.map(
            "TButton",
            background=[("active", UI["border"]), ("pressed", UI["border"])],
            foreground=[("disabled", "#98A2B3")],
        )
        style.configure(
            "Primary.TButton",
            font=UI["font_bold"],
            padding=(14, 9),
            background=UI["primary"],
            foreground=UI["primary_fg"],
        )
        style.map(
            "Primary.TButton",
            background=[
                ("active", UI["primary_hover"]),
                ("pressed", "#0B5F59"),
            ],
            foreground=[("disabled", "#D1D5DB")],
        )
        style.configure(
            "Danger.TButton",
            font=UI["font"],
            padding=(12, 8),
            background=UI["danger_bg"],
            foreground=UI["danger"],
        )
        style.map(
            "Danger.TButton",
            background=[("active", "#FEE4E2"), ("pressed", "#FECDCA")],
            foreground=[("active", UI["danger"])],
        )
        style.configure(
            "Ghost.TButton",
            font=UI["font"],
            padding=(12, 8),
            background=UI["surface"],
            foreground=UI["text"],
        )
        style.map(
            "Ghost.TButton",
            background=[("active", UI["surface_2"]), ("pressed", UI["border"])],
        )

        style.configure(
            "TCombobox",
            font=UI["font"],
            padding=6,
            fieldbackground=UI["surface"],
            background=UI["surface"],
        )
        style.configure(
            "TEntry",
            font=UI["font"],
            padding=6,
            fieldbackground=UI["surface"],
        )
        style.configure(
            "TNotebook",
            background=UI["bg"],
            borderwidth=0,
            # 上边距留给选中态更高的标签
            tabmargins=(12, 12, 12, 0),
        )
        # 未选中略矮；选中更高，避免「选中反而更矮」
        style.configure(
            "TNotebook.Tab",
            font=UI["font"],
            padding=(20, 7),
            background=UI["surface_2"],
            foreground=UI["muted"],
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", UI["surface"]), ("active", "#E4EBF2")],
            foreground=[("selected", UI["primary"]), ("active", UI["text"])],
            padding=[("selected", (22, 12, 22, 10)), ("!selected", (20, 7))],
            expand=[("selected", [1, 1, 1, 0])],
        )

        style.configure(
            "Game.Treeview",
            rowheight=40,
            font=UI["font"],
            background=UI["surface"],
            fieldbackground=UI["surface"],
            foreground=UI["text"],
            borderwidth=0,
            relief="flat",
        )
        style.configure(
            "Game.Treeview.Heading",
            font=UI["font_bold"],
            background=UI["header"],
            foreground=UI["header_fg"],
            padding=(10, 10),
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "Game.Treeview",
            background=[("selected", UI["select"])],
            foreground=[("selected", UI["text"])],
        )
        style.map(
            "Game.Treeview.Heading",
            background=[("active", UI["primary_hover"])],
            foreground=[("active", UI["header_fg"])],
        )

    def _style_tree_tags(self, tree: ttk.Treeview) -> None:
        tree.tag_configure("odd", background=UI["row_odd"], foreground=UI["text"])
        tree.tag_configure("even", background=UI["row_even"], foreground=UI["text"])
        tree.tag_configure(
            "invalid",
            background=UI["row_invalid"],
            foreground=UI["row_invalid_fg"],
        )

    @staticmethod
    def _center_window(win: tk.Toplevel | tk.Tk, width: int, height: int) -> None:
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max((sw - width) // 2, 0)
        y = max((sh - height) // 2, 0)
        win.geometry(f"{width}x{height}+{x}+{y}")

    def _build_ui(self) -> None:
        # 顶栏
        header = ttk.Frame(self, style="Header.TFrame", padding=(18, 14))
        header.pack(fill=tk.X)
        title_box = ttk.Frame(header, style="Header.TFrame")
        title_box.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(title_box, text="游戏运营后台", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            title_box,
            text="余额 · 本局核对 · 结算 · 抽水统计",
            style="Subtitle.TLabel",
        ).pack(anchor=tk.W, pady=(2, 0))

        actions = ttk.Frame(header, style="Header.TFrame")
        actions.pack(side=tk.RIGHT)
        ttk.Button(
            actions, text="刷新", command=self.refresh_all, style="Ghost.TButton"
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            actions, text="结算本局", command=self._on_settle, style="Primary.TButton"
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            actions,
            text="回退本局结算",
            command=self._rollback_last_settlement,
            style="Danger.TButton",
        ).pack(side=tk.LEFT, padx=4)

        room_bar = ttk.Frame(self, padding=(18, 10, 18, 4))
        room_bar.pack(fill=tk.X)
        ttk.Label(room_bar, text="当前群").pack(side=tk.LEFT)
        self.room_var = tk.StringVar(value=self.room_name)
        self.room_combo = ttk.Combobox(
            room_bar, textvariable=self.room_var, width=28, state="readonly"
        )
        self.room_combo.pack(side=tk.LEFT, padx=(8, 10))
        self.room_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_switch_room())
        ttk.Button(room_bar, text="新增群", command=self._add_room, style="Ghost.TButton").pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(room_bar, text="改名", command=self._rename_room, style="Ghost.TButton").pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(
            room_bar, text="删除群", command=self._delete_room, style="Danger.TButton"
        ).pack(side=tk.LEFT, padx=3)
        self._reload_room_combo()

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=14, pady=(6, 8))

        # 余额页
        bal_frame = ttk.Frame(notebook, style="Card.TFrame", padding=14)
        notebook.add(bal_frame, text="  用户余额  ")
        bal_btns = ttk.Frame(bal_frame, style="Card.TFrame")
        bal_btns.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(bal_btns, text="新增", command=self._add_player, style="Primary.TButton").pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(bal_btns, text="修改", command=self._edit_player, style="Ghost.TButton").pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(
            bal_btns, text="删除", command=self._delete_player, style="Danger.TButton"
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            bal_btns, text="导出余额", command=self._export_players, style="Ghost.TButton"
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            bal_btns, text="导入余额", command=self._import_players, style="Ghost.TButton"
        ).pack(side=tk.LEFT, padx=3)
        ttk.Label(
            bal_btns, text="导入时已存在用户将覆盖余额", style="CardMuted.TLabel"
        ).pack(side=tk.LEFT, padx=10)

        cols = ("nickname", "balance", "wxid", "updated_at")
        self.player_tree = ttk.Treeview(
            bal_frame, columns=cols, show="headings", height=16, style="Game.Treeview"
        )
        for c, title, w in (
            ("nickname", "用户", 180),
            ("balance", "余额", 120),
            ("wxid", "wxid", 260),
            ("updated_at", "更新时间", 180),
        ):
            self.player_tree.heading(c, text=title)
            self.player_tree.column(c, width=w, anchor=tk.W, minwidth=80)
        self.player_tree.pack(fill=tk.BOTH, expand=True)
        self._style_tree_tags(self.player_tree)

        # 本局下注页（底部操作栏固定，矮窗口也不被列表挤掉）
        bet_frame = ttk.Frame(notebook, style="Card.TFrame", padding=14)
        notebook.add(bet_frame, text="  本局下注  ")
        self.round_label = ttk.Label(bet_frame, text="当前局: -", style="Section.TLabel")
        self.round_label.pack(side=tk.TOP, anchor=tk.W)

        bet_footer = ttk.Frame(bet_frame, style="Card.TFrame")
        bet_footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        bet_btns = ttk.Frame(bet_footer, style="Card.TFrame")
        bet_btns.pack(fill=tk.X)
        ttk.Button(
            bet_btns,
            text="全部有效",
            command=lambda: self._set_all_bets_validity(True),
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            bet_btns,
            text="全部无效",
            command=lambda: self._set_all_bets_validity(False),
            style="Ghost.TButton",
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            bet_btns,
            text="生成核对列表",
            command=self._send_bet_checklist,
            style="Ghost.TButton",
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            bet_btns,
            text="作废本局",
            command=self._void_current_round,
            style="Danger.TButton",
        ).pack(side=tk.LEFT, padx=3)
        ttk.Label(
            bet_footer,
            text="双击行切换有效/无效 → 生成核对列表",
            style="CardMuted.TLabel",
        ).pack(anchor=tk.W, pady=(6, 0))

        bet_cols = ("check", "nickname", "amount", "valid", "reason", "updated_at")
        self.bet_tree = ttk.Treeview(
            bet_frame, columns=bet_cols, show="headings", height=8, style="Game.Treeview"
        )
        for c, title, w in (
            ("check", "本局有效", 90),
            ("nickname", "用户", 160),
            ("amount", "下注金额", 100),
            ("valid", "系统判定", 80),
            ("reason", "无效说明", 280),
            ("updated_at", "时间", 150),
        ):
            self.bet_tree.heading(c, text=title)
            self.bet_tree.column(c, width=w, anchor=tk.W, minwidth=60)
        self.bet_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(4, 0))
        self.bet_tree.bind("<Double-1>", self._on_bet_tree_toggle)
        self._style_tree_tags(self.bet_tree)

        # 结算结果页
        result_frame = ttk.Frame(notebook, style="Card.TFrame", padding=14)
        notebook.add(result_frame, text="  最近结算  ")
        result_top = ttk.Frame(result_frame, style="Card.TFrame")
        result_top.pack(fill=tk.X)
        self.result_label = ttk.Label(
            result_top, text="尚未结算", style="Section.TLabel"
        )
        self.result_label.pack(side=tk.LEFT, anchor=tk.W)
        ttk.Button(
            result_top,
            text="回退本局结算",
            command=self._rollback_last_settlement,
            style="Danger.TButton",
        ).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Label(
            result_frame,
            text="截图识别错误时可回退：恢复余额并把本局改回「已结束」，即可重新上传结算",
            style="CardMuted.TLabel",
        ).pack(anchor=tk.W, pady=(4, 0))
        res_cols = ("seq", "nickname", "bet", "point", "delta", "before", "after", "note")
        self.result_tree = ttk.Treeview(
            result_frame, columns=res_cols, show="headings", height=16, style="Game.Treeview"
        )
        for c, title, w in (
            ("seq", "序号", 60),
            ("nickname", "用户", 140),
            ("bet", "采购数量", 100),
            ("point", "采购结果", 90),
            ("delta", "采购加减", 100),
            ("before", "超市余额", 100),
            ("after", "剩余", 100),
            ("note", "备注", 220),
        ):
            self.result_tree.heading(c, text=title)
            self.result_tree.column(c, width=w, anchor=tk.W, minwidth=50)
        self.result_tree.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self._style_tree_tags(self.result_tree)

        # 后台统计（可滚动，避免未最大化时底部被裁切）
        stats_outer = ttk.Frame(notebook, style="Card.TFrame")
        notebook.add(stats_outer, text="  后台统计  ")
        stats_canvas = tk.Canvas(
            stats_outer, highlightthickness=0, bg=UI["surface"], bd=0
        )
        stats_scroll = ttk.Scrollbar(
            stats_outer, orient=tk.VERTICAL, command=stats_canvas.yview
        )
        stats_frame = ttk.Frame(stats_canvas, style="Card.TFrame", padding=16)
        stats_win = stats_canvas.create_window((0, 0), window=stats_frame, anchor=tk.NW)

        def _stats_sync_scroll(_event=None):
            stats_canvas.configure(scrollregion=stats_canvas.bbox("all"))

        def _stats_sync_width(event):
            stats_canvas.itemconfigure(stats_win, width=event.width)

        def _stats_on_mousewheel(event):
            # Windows: event.delta 为 ±120 的倍数
            stats_canvas.yview_scroll(int(-event.delta / 120), "units")

        stats_frame.bind("<Configure>", _stats_sync_scroll)
        stats_canvas.bind("<Configure>", _stats_sync_width)
        stats_canvas.bind("<Enter>", lambda _e: stats_canvas.bind_all("<MouseWheel>", _stats_on_mousewheel))
        stats_canvas.bind("<Leave>", lambda _e: stats_canvas.unbind_all("<MouseWheel>"))
        stats_canvas.configure(yscrollcommand=stats_scroll.set)
        stats_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        stats_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        stats_top = ttk.Frame(stats_frame, style="Card.TFrame")
        stats_top.pack(fill=tk.X)
        ttk.Label(stats_top, text="日期", style="Card.TLabel").pack(side=tk.LEFT)
        from datetime import datetime as _dt

        self.stats_date_var = tk.StringVar(value=_dt.now().strftime("%Y-%m-%d"))
        ttk.Entry(stats_top, textvariable=self.stats_date_var, width=12).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Button(
            stats_top, text="刷新统计", command=self._refresh_stats, style="Primary.TButton"
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            stats_top, text="导出抽水Excel", command=self._export_rake_xlsx, style="Primary.TButton"
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            stats_top,
            text="导出日汇总Excel",
            command=self._export_daily_summary_xlsx,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=3)
        ttk.Label(
            stats_top,
            text="右键抽水台账可下当局流水；右键玩家日汇总可下用户台账",
            style="CardMuted.TLabel",
        ).pack(side=tk.LEFT, padx=12)

        ttk.Label(
            stats_frame, text="玩家日汇总", style="Section.TLabel"
        ).pack(anchor=tk.W, pady=(10, 0))
        daily_cols = (
            "date",
            "nickname",
            "valid_bet",
            "valid_rounds",
            "invalid_rounds",
            "win_loss",
        )
        self.daily_tree = ttk.Treeview(
            stats_frame, columns=daily_cols, show="headings", height=7, style="Game.Treeview"
        )
        for c, title, w in (
            ("date", "日期", 100),
            ("nickname", "用户", 120),
            ("valid_bet", "有效下注", 100),
            ("valid_rounds", "有效局数", 80),
            ("invalid_rounds", "无效局数", 80),
            ("win_loss", "当日输赢", 100),
        ):
            self.daily_tree.heading(c, text=title)
            self.daily_tree.column(c, width=w, anchor=tk.W)
        self.daily_tree.pack(fill=tk.X, pady=4)
        self._style_tree_tags(self.daily_tree)
        self._bind_user_context_menu(self.daily_tree, nick_col_index=1)
        self._bind_user_context_menu(self.player_tree, nick_col_index=0)

        ttk.Label(stats_frame, text="单局抽水台账", style="Section.TLabel").pack(anchor=tk.W)
        rake_cols = ("id", "ended", "mode", "total", "rake", "pool")
        self.rake_tree = ttk.Treeview(
            stats_frame, columns=rake_cols, show="headings", height=6, style="Game.Treeview"
        )
        for c, title, w in (
            ("id", "局号", 60),
            ("ended", "结束时间", 150),
            ("mode", "模式", 60),
            ("total", "总下注", 90),
            ("rake", "抽水", 90),
            ("pool", "奖金池", 90),
        ):
            self.rake_tree.heading(c, text=title)
            self.rake_tree.column(c, width=w, anchor=tk.W)
        self.rake_tree.pack(fill=tk.X, pady=4)
        self._style_tree_tags(self.rake_tree)
        self._bind_round_context_menu(self.rake_tree)

        ttk.Label(stats_frame, text="上下分 / 对局流水", style="Section.TLabel").pack(
            anchor=tk.W
        )
        led_cols = ("time", "nick", "type", "change", "before", "after", "op", "remark")
        self.ledger_tree = ttk.Treeview(
            stats_frame, columns=led_cols, show="headings", height=8, style="Game.Treeview"
        )
        for c, title, w in (
            ("time", "时间", 140),
            ("nick", "用户", 100),
            ("type", "类型", 90),
            ("change", "变动", 80),
            ("before", "变动前", 80),
            ("after", "变动后", 80),
            ("op", "操作人", 70),
            ("remark", "备注", 200),
        ):
            self.ledger_tree.heading(c, text=title)
            self.ledger_tree.column(c, width=w, anchor=tk.W)
        self.ledger_tree.pack(fill=tk.X, pady=4)
        self._style_tree_tags(self.ledger_tree)
        # 底部留白，方便滚到末尾
        ttk.Frame(stats_frame, style="Card.TFrame", height=24).pack(fill=tk.X)

        status_bar = ttk.Frame(self, style="Status.TFrame")
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(
            status_bar, textvariable=self.status_var, style="Status.TLabel", anchor=tk.W
        ).pack(fill=tk.X)
        self._center_window(self, 1400, 900)

    @staticmethod
    def _mode_label(mode: Any) -> str:
        mapping = {
            "no_banker": "无庄",
            "banker": "有庄",
            "无庄": "无庄",
            "有庄": "有庄",
        }
        return mapping.get(str(mode or ""), str(mode or "-"))

    def _desktop_dir(self) -> Path:
        home = Path.home()
        for name in ("Desktop", "桌面"):
            p = home / name
            if p.is_dir():
                return p
        return home

    def _copy_image_to_clipboard(self, image_path: Path | str) -> bool:
        """把图片写入系统剪贴板，便于微信直接 Ctrl+V 粘贴发送。"""
        try:
            from omni_bot_sdk.utils.helpers import read_temp_image

            ok = bool(read_temp_image(str(image_path)))
            if not ok:
                logger.warning("复制图片到剪贴板失败: %s", image_path)
            return ok
        except Exception:
            logger.exception("复制图片到剪贴板异常: %s", image_path)
            return False

    def _save_report_to_desktop(
        self, report_path: Path | str, *, copy_clipboard: bool = True
    ) -> tuple[Path, bool]:
        """报表图复制到桌面；默认同时写入剪贴板。返回 (桌面路径, 是否已复制剪贴板)。"""
        src = Path(report_path)
        desktop = self._desktop_dir()
        desktop.mkdir(parents=True, exist_ok=True)
        dest = desktop / src.name
        # 重名则加序号
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            i = 1
            while True:
                cand = desktop / f"{stem}_{i}{suffix}"
                if not cand.exists():
                    dest = cand
                    break
                i += 1
        import shutil

        shutil.copy2(src, dest)
        clipped = False
        if copy_clipboard:
            clipped = self._copy_image_to_clipboard(dest)
        return dest, clipped

    def _reload_room_combo(self) -> None:
        rooms = self.store.list_game_rooms()
        self.room_combo["values"] = rooms
        if self.room_name and self.room_name in rooms:
            self.room_var.set(self.room_name)
        elif rooms:
            self.room_name = rooms[0]
            self.room_var.set(self.room_name)
        else:
            self.room_name = ""
            self.room_var.set("")

    def _on_switch_room(self) -> None:
        self.room_name = self.room_var.get().strip()
        self.title(f"游戏后台 · {self.room_name or '未选择群'}")
        self.refresh_all()

    def _add_room(self) -> None:
        name = simpledialog.askstring("新增群", "群名称（与微信群名一致）:", parent=self)
        if not name or not name.strip():
            return
        try:
            self.store.add_game_room(name.strip())
        except Exception as e:
            messagebox.showerror("失败", str(e), parent=self)
            return
        self.room_name = name.strip()
        self._reload_room_combo()
        self._on_switch_room()
        self.status_var.set(f"已新增群: {self.room_name}")

    def _rename_room(self) -> None:
        old = self.room_var.get().strip()
        if not old:
            messagebox.showwarning("提示", "请先选择群", parent=self)
            return
        new = simpledialog.askstring(
            "改名", f"将「{old}」改为:", initialvalue=old, parent=self
        )
        if not new or not new.strip() or new.strip() == old:
            return
        try:
            self.store.rename_game_room(old, new.strip())
        except Exception as e:
            messagebox.showerror("失败", str(e), parent=self)
            return
        self.room_name = new.strip()
        self._reload_room_combo()
        self._on_switch_room()
        self.status_var.set(f"群已改名: {old} → {self.room_name}")

    def _delete_room(self) -> None:
        name = self.room_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请先选择群", parent=self)
            return
        if not messagebox.askyesno(
            "确认删除",
            f"从管理列表删除群「{name}」？\n（不会删除该群已有余额/对局数据）",
            parent=self,
        ):
            return
        self.store.delete_game_room(name)
        self._reload_room_combo()
        self._on_switch_room()
        self.status_var.set(f"已删除群: {name}")

    def refresh_all(self) -> None:
        self._reload_room_combo()
        self._refresh_players()
        self._refresh_bets()
        self._refresh_last_settlement()
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        day = (self.stats_date_var.get() or "").strip()
        for i in self.daily_tree.get_children():
            self.daily_tree.delete(i)
        for idx, row in enumerate(
            self.store.player_daily_summary(self.room_name, day)
        ):
            self.daily_tree.insert(
                "",
                tk.END,
                values=(
                    row.get("date"),
                    row.get("nickname"),
                    row.get("valid_bet_amount"),
                    row.get("valid_round_count"),
                    row.get("invalid_round_count"),
                    row.get("win_loss"),
                ),
                tags=("even" if idx % 2 else "odd",),
            )

        for i in self.rake_tree.get_children():
            self.rake_tree.delete(i)
        for idx, row in enumerate(
            self.store.list_rake_ledger(self.room_name, day, day)
        ):
            rid = str(row.get("id"))
            self.rake_tree.insert(
                "",
                tk.END,
                iid=f"round-{rid}",
                values=(
                    row.get("id"),
                    row.get("ended_at") or row.get("started_at"),
                    self._mode_label(row.get("mode")),
                    row.get("total_bet"),
                    row.get("rake_amount"),
                    row.get("pool_amount"),
                ),
                tags=("even" if idx % 2 else "odd",),
            )

        for i in self.ledger_tree.get_children():
            self.ledger_tree.delete(i)
        for idx, row in enumerate(
            self.store.list_ledger(self.room_name, date_from=day, date_to=day, limit=200)
        ):
            self.ledger_tree.insert(
                "",
                tk.END,
                values=(
                    row.get("created_at"),
                    row.get("nickname"),
                    row.get("type"),
                    f"{float(row.get('change_amount') or 0):+.2f}",
                    f"{float(row.get('balance_before') or 0):.2f}",
                    f"{float(row.get('balance_after') or 0):.2f}",
                    row.get("operator") or "",
                    row.get("remark") or "",
                ),
                tags=("even" if idx % 2 else "odd",),
            )

    def _bind_round_context_menu(self, tree: ttk.Treeview) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="下载当局流水表格",
            command=lambda: self._export_selected_round_flow(tree),
        )

        def popup(event):
            row = tree.identify_row(event.y)
            if row:
                tree.selection_set(row)
                menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", popup)

    def _bind_user_context_menu(self, tree: ttk.Treeview, nick_col_index: int = 0) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="下载该用户最近流水台账",
            command=lambda: self._export_selected_user_ledger(tree, nick_col_index),
        )

        def popup(event):
            row = tree.identify_row(event.y)
            if row:
                tree.selection_set(row)
                menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", popup)

    def _export_rake_xlsx(self) -> None:
        from datetime import datetime as _dt

        from omni_bot_sdk.game.export_xlsx import export_styled_table

        day = (self.stats_date_var.get() or "").strip() or _dt.now().strftime("%Y-%m-%d")
        rows = self.store.list_rake_ledger(self.room_name, day, day)
        headers = ["局号", "群名称", "对局时间", "模式", "总下注", "抽水金额", "奖金池", "庄家"]
        data = []
        for r in rows:
            data.append(
                [
                    r.get("id"),
                    r.get("room_name") or self.room_name,
                    r.get("ended_at") or r.get("started_at") or "",
                    self._mode_label(r.get("mode")),
                    r.get("total_bet"),
                    r.get("rake_amount"),
                    r.get("pool_amount"),
                    r.get("banker_name") or "",
                ]
            )
        safe_room = self.room_name or "全部群"
        path = Path(self.engine.report_dir) / f"抽水台账_{safe_room}_{day}.xlsx"
        export_styled_table(
            path,
            headers,
            data,
            title=f"{safe_room} 抽水台账 {day}",
            col_widths={
                "局号": 10,
                "群名称": 18,
                "对局时间": 20,
                "模式": 10,
                "总下注": 12,
                "抽水金额": 12,
                "奖金池": 12,
                "庄家": 14,
            },
        )
        messagebox.showinfo("导出完成", f"已导出: {path}", parent=self)
        self.status_var.set(f"已导出抽水台账: {path}")

    def _export_daily_summary_xlsx(self) -> None:
        from datetime import datetime as _dt

        from omni_bot_sdk.game.export_xlsx import export_styled_table

        day = (self.stats_date_var.get() or "").strip() or _dt.now().strftime("%Y-%m-%d")
        rows = self.store.player_daily_summary(self.room_name, day)
        if not rows:
            messagebox.showinfo("提示", f"{day} 没有可导出的玩家日汇总", parent=self)
            return
        headers = ["日期", "用户", "有效下注", "有效局数", "无效局数", "当日输赢"]
        data = []
        for r in rows:
            data.append(
                [
                    r.get("date") or day,
                    r.get("nickname") or "",
                    r.get("valid_bet_amount"),
                    r.get("valid_round_count"),
                    r.get("invalid_round_count"),
                    r.get("win_loss"),
                ]
            )
        safe_room = self.room_name or "全部群"
        path = Path(self.engine.report_dir) / f"玩家日汇总_{safe_room}_{day}.xlsx"
        export_styled_table(
            path,
            headers,
            data,
            title=f"{safe_room} 玩家日汇总 {day}",
            col_widths={
                "日期": 12,
                "用户": 18,
                "有效下注": 12,
                "有效局数": 10,
                "无效局数": 10,
                "当日输赢": 12,
            },
        )
        messagebox.showinfo("导出完成", f"已导出: {path}", parent=self)
        self.status_var.set(f"已导出玩家日汇总: {path}")

    def _export_selected_round_flow(self, tree: ttk.Treeview) -> None:
        from omni_bot_sdk.game.export_xlsx import export_styled_table

        sel = tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一局", parent=self)
            return
        values = tree.item(sel[0], "values")
        if not values:
            return
        try:
            round_id = int(values[0])
        except (TypeError, ValueError):
            messagebox.showerror("错误", "无法识别局号", parent=self)
            return

        rnd = self.store.get_round(round_id)
        settle_rows = self.store.list_settlement_rows(round_id)
        if not settle_rows:
            messagebox.showinfo("提示", f"局#{round_id} 没有结算流水", parent=self)
            return

        headers = [
            "序号",
            "对局",
            "对局时间",
            "模式",
            "用户",
            "采购数量",
            "采购结果",
            "红包金额",
            "结算前余额",
            "加减情况",
            "结算后余额",
            "备注",
        ]
        mode = self._mode_label((rnd or {}).get("mode"))
        round_time = (rnd or {}).get("ended_at") or (rnd or {}).get("started_at") or ""
        banker_name = ((rnd or {}).get("banker_name") or "").strip()
        data = []
        for r in settle_rows:
            delta = float(r.get("delta") or 0)
            note = r.get("note") or ""
            bet_show = (
                "庄家"
                if note.startswith("庄家")
                or (
                    banker_name
                    and str(r.get("nickname") or "").strip() == banker_name
                )
                else r.get("bet_amount")
            )
            data.append(
                [
                    r.get("seq"),
                    f"第{round_id}局",
                    round_time,
                    mode,
                    r.get("nickname"),
                    bet_show,
                    r.get("point"),
                    r.get("packet_amount"),
                    r.get("balance_before"),
                    f"{delta:+.2f}",
                    r.get("balance_after"),
                    note,
                ]
            )
        room = (rnd or {}).get("room_name") or self.room_name or "群"
        path = Path(self.engine.report_dir) / f"当局流水_第{round_id}局_{room}.xlsx"
        export_styled_table(
            path,
            headers,
            data,
            title=(
                f"{room} 第{round_id}局流水  模式={mode}  "
                f"总下注={(rnd or {}).get('total_bet')}  "
                f"抽水={(rnd or {}).get('rake_amount')}  "
                f"奖金池={(rnd or {}).get('pool_amount')}"
            ),
            col_widths={
                "序号": 8,
                "对局": 12,
                "对局时间": 20,
                "模式": 10,
                "用户": 14,
                "采购数量": 12,
                "采购结果": 10,
                "红包金额": 12,
                "结算前余额": 12,
                "加减情况": 12,
                "结算后余额": 12,
                "备注": 28,
            },
        )
        messagebox.showinfo("导出完成", f"已导出当局流水:\n{path}", parent=self)
        self.status_var.set(f"已导出当局流水: {path}")

    def _export_selected_user_ledger(
        self, tree: ttk.Treeview, nick_col_index: int = 0
    ) -> None:
        from omni_bot_sdk.game.export_xlsx import export_styled_table

        sel = tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中用户", parent=self)
            return
        values = tree.item(sel[0], "values")
        if not values or len(values) <= nick_col_index:
            return
        nickname = str(values[nick_col_index]).strip()
        if not nickname:
            return

        history = self.store.list_player_settlement_history(
            nickname, self.room_name, limit=200
        )
        # 同时附上最近账本流水（上分下分等）
        ledgers = self.store.list_ledger(
            room_name=self.room_name, nickname=nickname, limit=200
        )
        if not history and not ledgers:
            messagebox.showinfo("提示", f"用户 {nickname} 暂无流水", parent=self)
            return

        safe_nick = "".join(
            ch if ch.isalnum() or "\u4e00" <= ch <= "\u9fff" else "_"
            for ch in nickname
        )
        path = (
            Path(self.engine.report_dir)
            / f"用户流水_{safe_nick}_{self.room_name or '群'}.xlsx"
        )
        room_label = self.room_name or "全部"

        if history:
            headers = [
                "对局",
                "对局时间",
                "模式",
                "庄家",
                "采购数量",
                "采购结果",
                "结算前余额",
                "加减情况",
                "结算后余额",
                "备注",
            ]
            data = []
            for r in history:
                delta = float(r.get("delta") or 0)
                note = r.get("note") or ""
                bet_show = (
                    "庄家"
                    if note.startswith("庄家")
                    or (
                        (r.get("banker_name") or "").strip()
                        and str(r.get("nickname") or "").strip()
                        == str(r.get("banker_name") or "").strip()
                    )
                    else r.get("bet_amount")
                )
                data.append(
                    [
                        f"第{r.get('round_id')}局",
                        r.get("ended_at") or r.get("started_at") or "",
                        self._mode_label(r.get("mode")),
                        r.get("banker_name") or "",
                        bet_show,
                        r.get("point"),
                        r.get("balance_before"),
                        f"{delta:+.2f}",
                        r.get("balance_after"),
                        note,
                    ]
                )
            export_styled_table(
                path,
                headers,
                data,
                title=f"用户 {nickname} 最近对局流水台账（群：{room_label}）",
                col_widths={
                    "对局": 12,
                    "对局时间": 20,
                    "模式": 10,
                    "庄家": 12,
                    "采购数量": 12,
                    "采购结果": 10,
                    "结算前余额": 12,
                    "加减情况": 12,
                    "结算后余额": 12,
                    "备注": 28,
                },
            )
        else:
            # 无对局记录时，账本作为主表
            led_headers = [
                "时间",
                "类型",
                "变动金额",
                "结算前余额",
                "结算后余额",
                "操作人",
                "关联局号",
                "备注",
            ]
            led_data = [
                [
                    led.get("created_at"),
                    led.get("type"),
                    f"{float(led.get('change_amount') or 0):+.2f}",
                    led.get("balance_before"),
                    led.get("balance_after"),
                    led.get("operator") or "",
                    led.get("round_id") or "",
                    led.get("remark") or "",
                ]
                for led in ledgers
            ]
            export_styled_table(
                path,
                led_headers,
                led_data,
                title=f"用户 {nickname} 账本流水（群：{room_label}）",
                col_widths={
                    "时间": 18,
                    "类型": 12,
                    "变动金额": 12,
                    "结算前余额": 12,
                    "结算后余额": 12,
                    "操作人": 10,
                    "关联局号": 10,
                    "备注": 28,
                },
            )
            ledgers = []  # 已写入主表，不再追加第二页

        # 第二页：账本（上分/下分/调账）
        if ledgers and history:
            try:
                from openpyxl import load_workbook
                from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
                from openpyxl.utils import get_column_letter

                wb = load_workbook(path)
                ws = wb.create_sheet("账本流水")
                led_headers = [
                    "时间",
                    "类型",
                    "变动金额",
                    "结算前余额",
                    "结算后余额",
                    "操作人",
                    "关联局号",
                    "备注",
                ]
                header_fill = PatternFill("solid", fgColor="1F4E79")
                header_font = Font(bold=True, color="FFFFFF", size=12, name="微软雅黑")
                white_fill = PatternFill("solid", fgColor="FFFFFF")
                blue_fill = PatternFill("solid", fgColor="DDEBF7")
                cell_font = Font(size=11, name="微软雅黑")
                thin = Border(
                    left=Side(style="thin", color="B4B4B4"),
                    right=Side(style="thin", color="B4B4B4"),
                    top=Side(style="thin", color="B4B4B4"),
                    bottom=Side(style="thin", color="B4B4B4"),
                )
                center = Alignment(
                    horizontal="center", vertical="center", wrap_text=True
                )
                for col, h in enumerate(led_headers, start=1):
                    cell = ws.cell(row=1, column=col, value=h)
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = center
                    cell.border = thin
                for i, led in enumerate(ledgers):
                    fill = white_fill if i % 2 == 0 else blue_fill
                    vals = [
                        led.get("created_at"),
                        led.get("type"),
                        f"{float(led.get('change_amount') or 0):+.2f}",
                        led.get("balance_before"),
                        led.get("balance_after"),
                        led.get("operator") or "",
                        led.get("round_id") or "",
                        led.get("remark") or "",
                    ]
                    for col, v in enumerate(vals, start=1):
                        cell = ws.cell(row=2 + i, column=col, value=v)
                        cell.fill = fill
                        cell.font = cell_font
                        cell.alignment = center
                        cell.border = thin
                for col, w in enumerate([18, 12, 12, 12, 12, 10, 10, 28], start=1):
                    ws.column_dimensions[get_column_letter(col)].width = w
                wb.save(path)
            except Exception as e:
                logger.warning(f"写入账本页失败: {e}")

        messagebox.showinfo("导出完成", f"已导出用户流水:\n{path}", parent=self)
        self.status_var.set(f"已导出用户流水: {path}")

    def _refresh_players(self) -> None:
        for i in self.player_tree.get_children():
            self.player_tree.delete(i)
        for idx, p in enumerate(self.store.list_players(self.room_name)):
            self.player_tree.insert(
                "",
                tk.END,
                values=(
                    p.get("nickname"),
                    f"{float(p.get('balance') or 0):.2f}",
                    p.get("wxid") or "",
                    p.get("updated_at") or "",
                ),
                tags=("even" if idx % 2 else "odd",),
            )

    def _current_review_round(self) -> Optional[Dict[str, Any]]:
        """优先取采集中/已结束未结算局；已结算/作废不用于核对。"""
        if not self.room_name:
            return None
        active = self.store.get_active_round(self.room_name)
        if active:
            return active
        ended = self.store.get_latest_ended_round(self.room_name)
        if ended and ended.get("status") == "ended":
            return ended
        return None

    @staticmethod
    def _format_bet_reason(bet: Dict[str, Any], min_bet: float = 50) -> str:
        """核对列表用的无效说明文案。"""
        if bool(bet.get("is_valid")):
            return "—"
        reason = str(bet.get("invalid_reason") or "").strip()
        content = str(bet.get("content") or "").strip()
        if not reason:
            return "—"
        if "余额为零" in reason or "未维护" in reason:
            return "下注无效余额为零 请上分"
        if "低于最低" in reason:
            return reason if "限制" in reason else f"下注金额低于最低 {min_bet:g} 限制"
        if "大于玩家当前账户" in reason or "余额不足" in reason:
            return "下注金额大于玩家当前账户积分"
        if "玩家主动无效" in reason or content in {"无效", "取消", "不压"}:
            word = content if content in {"无效", "取消", "不压"} else "无效"
            return f"玩家发送文字「{word}」撤注"
        if "作废" in reason:
            return reason
        if "结束后" in reason or "迟到" in reason:
            return "答题结束后才收到下注消息"
        return reason

    def _refresh_bets(self) -> None:
        for i in self.bet_tree.get_children():
            self.bet_tree.delete(i)
        rnd = self._current_review_round()
        if not rnd and self.room_name:
            # 展示最近一局（含已结算/作废）便于查看
            rnd = self.store.get_latest_ended_round(self.room_name)
            if not rnd:
                rounds = self.store.list_rounds(self.room_name, limit=1)
                rnd = rounds[0] if rounds else None
        if not rnd:
            self.round_label.config(text="当前局: 无")
            return
        status_cn = {
            "collecting": "采集中",
            "ended": "已结束",
            "settled": "已结算",
            "voided": "已作废",
        }.get(str(rnd.get("status") or ""), str(rnd.get("status") or "-"))
        self.round_label.config(
            text=(
                f"当前局: #{rnd['id']} 状态={status_cn} "
                f"开始={rnd.get('started_at')} 结束={rnd.get('ended_at') or '-'}"
            )
        )
        for idx, b in enumerate(self.store.list_bets(int(rnd["id"]))):
            valid = bool(b.get("is_valid"))
            tag = "invalid" if not valid else ("even" if idx % 2 else "odd")
            self.bet_tree.insert(
                "",
                tk.END,
                iid=f"{rnd['id']}|{b.get('nickname')}",
                values=(
                    "☑" if valid else "☐",
                    b.get("nickname"),
                    f"{float(b.get('amount') or 0):.2f}",
                    "有效" if valid else "无效",
                    self._format_bet_reason(b, self.min_bet),
                    b.get("updated_at") or "",
                ),
                tags=(tag,),
            )

    def _refresh_last_settlement(self) -> None:
        for i in self.result_tree.get_children():
            self.result_tree.delete(i)
        rnd = self.store.get_latest_ended_round(self.room_name)
        if not rnd or rnd.get("status") != "settled":
            # 找最近 settled
            rounds = self.store.list_rounds(self.room_name, limit=20)
            rnd = next((r for r in rounds if r.get("status") == "settled"), None)
        if not rnd:
            self.result_label.config(text="尚未结算")
            return
        rows = self.store.list_settlement_rows(int(rnd["id"]))
        self.result_label.config(
            text=(
                f"局#{rnd['id']} 模式={self._mode_label(rnd.get('mode'))} "
                f"庄家={rnd.get('banker_name') or '-'} "
                f"抽水={rnd.get('rake_percent')}% 报表={rnd.get('report_path') or '-'}"
            )
        )
        banker_name = (rnd.get("banker_name") or "").strip()
        for idx, r in enumerate(rows):
            note = r.get("note") or ""
            is_banker_row = bool(banker_name) and (
                str(r.get("nickname") or "").strip() == banker_name
                and (note.startswith("庄家") or idx == 0)
            )
            # 有庄模式：庄家采购数量显示「庄家」
            if is_banker_row or note.startswith("庄家"):
                bet_show = "庄家"
            else:
                bet_show = f"{float(r.get('bet_amount') or 0):.2f}"
            delta_v = float(r.get("delta") or 0)
            invalid = any(
                k in note
                for k in (
                    "无效",
                    "失败",
                    "低于最低",
                    "未维护",
                    "余额为零",
                    "仅统计",
                    "判负",
                    "判输",
                    "奖金池不足",
                    "人工判定",
                )
            ) or delta_v < -1e-9
            tag = "invalid" if invalid else ("even" if idx % 2 else "odd")
            self.result_tree.insert(
                "",
                tk.END,
                values=(
                    r.get("seq"),
                    r.get("nickname"),
                    bet_show,
                    r.get("point"),
                    f"{delta_v:+.2f}",
                    f"{float(r.get('balance_before') or 0):.2f}",
                    f"{float(r.get('balance_after') or 0):.2f}",
                    note,
                ),
                tags=(tag,),
            )

    def _selected_player(self) -> Optional[str]:
        sel = self.player_tree.selection()
        if not sel:
            return None
        return str(self.player_tree.item(sel[0], "values")[0])

    def _player_form_dialog(
        self,
        title: str,
        initial_nick: str = "",
        initial_balance: float = 0.0,
        nick_editable: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """单个弹窗填写用户名 + 余额。确认返回 {nickname, balance}，取消返回 None。"""
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=UI["bg"])
        win.transient(self)
        win.resizable(True, False)
        win.minsize(560, 280)
        win.grab_set()
        win.focus_force()
        win.lift()

        result: Dict[str, Any] = {}

        form = ttk.Frame(win, padding=26)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="用户名称").grid(row=0, column=0, sticky=tk.W, pady=12)
        nick_var = tk.StringVar(value=initial_nick)
        nick_entry = ttk.Entry(form, textvariable=nick_var)
        nick_entry.grid(row=0, column=1, sticky=tk.EW, padx=(12, 0), pady=12)
        if not nick_editable:
            nick_entry.configure(state="readonly")

        ttk.Label(form, text="余额").grid(row=1, column=0, sticky=tk.W, pady=12)
        bal_var = tk.StringVar(value=f"{float(initial_balance):.2f}")
        bal_entry = ttk.Entry(form, textvariable=bal_var)
        bal_entry.grid(row=1, column=1, sticky=tk.EW, padx=(12, 0), pady=12)

        btns = ttk.Frame(form)
        btns.grid(row=2, column=0, columnspan=2, pady=(22, 4), sticky=tk.E)

        def on_ok() -> None:
            nick = nick_var.get().strip()
            if not nick:
                messagebox.showerror("错误", "请填写用户名称", parent=win)
                return
            try:
                bal = float(str(bal_var.get()).replace(",", "").strip() or "0")
            except ValueError:
                messagebox.showerror("错误", "余额必须是数字", parent=win)
                return
            result["nickname"] = nick
            result["balance"] = bal
            win.destroy()

        def on_cancel() -> None:
            win.destroy()

        ttk.Button(btns, text="取消", command=on_cancel, style="Ghost.TButton").pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(btns, text="确定", command=on_ok, style="Primary.TButton").pack(
            side=tk.LEFT, padx=6
        )

        # 按内容估算后再居中，避免高 DPI 下控件被裁切
        win.update_idletasks()
        need_w = max(560, win.winfo_reqwidth() + 48)
        need_h = max(280, win.winfo_reqheight() + 28)
        self._center_window(win, need_w, need_h)

        nick_entry.focus_set()
        win.bind("<Return>", lambda _e: on_ok())
        win.bind("<Escape>", lambda _e: on_cancel())
        win.wait_window()
        return result or None

    def _add_player(self) -> None:
        data = self._player_form_dialog("新增用户", initial_nick="", initial_balance=0.0)
        if not data:
            return
        try:
            self.store.add_player(
                data["nickname"], float(data["balance"]), self.room_name
            )
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("失败", str(e), parent=self)

    def _export_players(self) -> None:
        from datetime import datetime as _dt

        from omni_bot_sdk.game.export_xlsx import export_styled_table

        players = self.store.list_players(self.room_name)
        if not players:
            messagebox.showinfo("提示", "当前没有可导出的用户", parent=self)
            return
        headers = ["用户", "余额", "wxid", "群名称", "更新时间"]
        data = [
            [
                p.get("nickname") or "",
                float(p.get("balance") or 0),
                p.get("wxid") or "",
                p.get("room_name") or self.room_name or "",
                p.get("updated_at") or "",
            ]
            for p in players
        ]
        day = _dt.now().strftime("%Y%m%d_%H%M%S")
        room = self.room_name or "全部群"
        path = Path(self.engine.report_dir) / f"用户余额_{room}_{day}.xlsx"
        chosen = filedialog.asksaveasfilename(
            parent=self,
            title="导出用户余额",
            defaultextension=".xlsx",
            initialfile=path.name,
            filetypes=[("Excel 文件", "*.xlsx")],
        )
        if not chosen:
            return
        export_styled_table(
            chosen,
            headers,
            data,
            title=f"{room} 用户余额导出",
            col_widths={
                "用户": 18,
                "余额": 12,
                "wxid": 28,
                "群名称": 18,
                "更新时间": 20,
            },
        )
        messagebox.showinfo("导出完成", f"已导出 {len(data)} 名用户:\n{chosen}", parent=self)
        self.status_var.set(f"已导出用户余额: {chosen}")

    def _import_players(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="导入用户余额",
            filetypes=[
                ("Excel/CSV", "*.xlsx;*.xls;*.csv"),
                ("Excel 文件", "*.xlsx;*.xls"),
                ("CSV 文件", "*.csv"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        try:
            rows = self._parse_player_import_file(path)
        except Exception as e:
            messagebox.showerror("导入失败", f"读取文件失败:\n{e}", parent=self)
            return
        if not rows:
            messagebox.showinfo("提示", "文件中没有有效的用户数据", parent=self)
            return

        ok = messagebox.askyesno(
            "确认导入",
            f"将导入 {len(rows)} 条用户余额。\n已存在用户会覆盖余额，是否继续？",
            parent=self,
        )
        if not ok:
            return

        created = 0
        updated = 0
        failed = 0
        errors: List[str] = []
        for item in rows:
            nick = item["nickname"]
            try:
                action = self.store.upsert_player(
                    nick,
                    float(item["balance"]),
                    self.room_name,
                    wxid=item.get("wxid") or "",
                    remark="余额导入覆盖",
                    operator="gui",
                )
                if action == "created":
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                failed += 1
                if len(errors) < 8:
                    errors.append(f"{nick}: {e}")

        self.refresh_all()
        msg = f"导入完成：新增 {created}，覆盖 {updated}"
        if failed:
            msg += f"，失败 {failed}"
            if errors:
                msg += "\n" + "\n".join(errors)
        messagebox.showinfo("导入结果", msg, parent=self)
        self.status_var.set(msg)

    def _parse_player_import_file(self, path: str) -> List[Dict[str, Any]]:
        """解析 xlsx/csv，表头支持：用户/昵称/nickname、余额/balance、wxid。"""
        p = Path(path)
        suffix = p.suffix.lower()
        raw_rows: List[Dict[str, Any]] = []

        if suffix == ".csv":
            import csv

            with open(p, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    raw_rows.append({str(k).strip(): v for k, v in row.items() if k})
        else:
            from openpyxl import load_workbook

            wb = load_workbook(p, data_only=True)
            ws = wb.active
            headers: List[str] = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                cells = ["" if c is None else str(c).strip() for c in row]
                if not any(cells):
                    continue
                if not headers:
                    # 跳过标题行：若首行不像表头则继续找
                    lower = [c.lower() for c in cells]
                    if any(
                        h in lower or h in cells
                        for h in (
                            "用户",
                            "昵称",
                            "nickname",
                            "余额",
                            "balance",
                            "wxid",
                        )
                    ):
                        headers = cells
                    continue
                item = {}
                for idx, h in enumerate(headers):
                    if idx < len(cells):
                        item[h] = cells[idx]
                raw_rows.append(item)

        nick_keys = ("用户", "昵称", "用户昵称", "nickname", "nick", "name", "玩家")
        bal_keys = ("余额", "balance", "金额", "分数", "积分")
        wxid_keys = ("wxid", "微信id", "微信ID", "wx_id")

        def pick(row: Dict[str, Any], keys: tuple) -> Any:
            lower_map = {str(k).strip().lower(): v for k, v in row.items()}
            for k in keys:
                if k in row and row[k] not in (None, ""):
                    return row[k]
                if k.lower() in lower_map and lower_map[k.lower()] not in (None, ""):
                    return lower_map[k.lower()]
            return None

        by_nick: Dict[str, Dict[str, Any]] = {}
        for row in raw_rows:
            nick_raw = pick(row, nick_keys)
            bal_raw = pick(row, bal_keys)
            if nick_raw is None or bal_raw is None:
                continue
            nick = str(nick_raw).strip()
            if not nick:
                continue
            try:
                bal = float(str(bal_raw).replace(",", "").strip())
            except (TypeError, ValueError):
                continue
            wxid_raw = pick(row, wxid_keys)
            wxid = str(wxid_raw).strip() if wxid_raw is not None else ""
            # 同文件重复用户：后出现的覆盖前面的
            by_nick[nick] = {"nickname": nick, "balance": bal, "wxid": wxid}
        return list(by_nick.values())

    def _edit_player(self) -> None:
        nick = self._selected_player()
        if not nick:
            messagebox.showinfo("提示", "请先选择用户", parent=self)
            return
        player = self.store.get_player(nick, self.room_name)
        cur = float((player or {}).get("balance") or 0)
        data = self._player_form_dialog(
            "修改用户",
            initial_nick=nick,
            initial_balance=cur,
            nick_editable=True,
        )
        if not data:
            return
        new_nick = data["nickname"]
        new_bal = float(data["balance"])
        try:
            if new_nick != nick:
                self.store.rename_player(nick, new_nick, self.room_name)
                nick = new_nick
            if abs(new_bal - cur) > 1e-9:
                self.store.set_balance(
                    nick, new_bal, self.room_name, remark="GUI修改余额"
                )
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("失败", str(e), parent=self)

    def _delete_player(self) -> None:
        nick = self._selected_player()
        if not nick:
            messagebox.showinfo("提示", "请先选择用户", parent=self)
            return
        if not messagebox.askyesno("确认", f"删除用户 {nick}？", parent=self):
            return
        self.store.delete_player(nick, self.room_name)
        self.refresh_all()

    def _on_bet_tree_toggle(self, _event=None) -> None:
        """双击切换本局有效勾选（人工覆盖）。"""
        sel = self.bet_tree.selection()
        if not sel:
            return
        iid = sel[0]
        if "|" not in str(iid):
            return
        round_id_s, nick = str(iid).split("|", 1)
        try:
            round_id = int(round_id_s)
        except ValueError:
            return
        bet = next(
            (
                b
                for b in self.store.list_bets(round_id, valid_only=False)
                if str(b.get("nickname") or "") == nick
            ),
            None,
        )
        if not bet:
            return
        rnd = self.store.get_round(round_id)
        if rnd and rnd.get("status") in ("settled", "voided"):
            messagebox.showinfo("提示", "该局已结算或作废，不能再改有效性", parent=self)
            return
        new_valid = not bool(bet.get("is_valid"))
        if new_valid:
            reason = ""
        else:
            old_reason = str(bet.get("invalid_reason") or "").strip()
            # 原有效→人工改无效；原无效保持系统原因
            reason = old_reason if (not bool(bet.get("is_valid")) and old_reason) else "人工判定无效"
        self.store.set_bet_validity(round_id, nick, new_valid, reason)
        self._refresh_bets()

    def _set_all_bets_validity(self, is_valid: bool) -> None:
        """本局下注页：一键全部有效 / 全部无效（人工覆盖）。"""
        rnd = self._current_review_round()
        if not rnd:
            messagebox.showinfo(
                "提示",
                "没有可核对的对局（需采集中或已结束未结算）",
                parent=self,
            )
            return
        if rnd.get("status") in ("settled", "voided"):
            messagebox.showinfo("提示", "该局已结算或作废，不能再改有效性", parent=self)
            return
        round_id = int(rnd["id"])
        bets = self.store.list_bets(round_id, valid_only=False)
        if not bets:
            messagebox.showinfo("提示", f"局#{round_id} 暂无下注记录", parent=self)
            return
        label = "全部有效" if is_valid else "全部无效"
        for bet in bets:
            nick = str(bet.get("nickname") or "")
            if not nick:
                continue
            if is_valid:
                self.store.set_bet_validity(round_id, nick, True, "")
            else:
                old = str(bet.get("invalid_reason") or "").strip()
                reason = old or "人工判定无效"
                self.store.set_bet_validity(round_id, nick, False, reason)
        self._refresh_bets()
        self.status_var.set(f"局#{round_id} 已设为{label}")

    def _build_bet_checklist_rows(
        self, bets: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for idx, bet in enumerate(bets, start=1):
            valid = bool(bet.get("is_valid"))
            rows.append(
                {
                    "序号": idx,
                    "用户账号 ID": bet.get("nickname") or "",
                    "下注金额": round(float(bet.get("amount") or 0), 2),
                    "有效性": "有效" if valid else "无效",
                    "无效说明": self._format_bet_reason(bet, self.min_bet),
                    "_invalid": not valid,
                }
            )
        return rows

    def _send_bet_checklist(self, round_id: Optional[int] = None) -> None:
        """先选结算模式（有庄校验余额），再生成核对列表到桌面。"""
        if round_id is None:
            rnd = self._current_review_round()
            if not rnd:
                messagebox.showinfo("提示", "没有可生成核对列表的对局", parent=self)
                return
            round_id = int(rnd["id"])
        bets = self.store.list_bets(int(round_id), valid_only=False)
        if not bets:
            messagebox.showinfo("提示", "本局暂无下注玩家", parent=self)
            return

        def _after_mode(mode: str, banker: str, rake: float) -> None:
            self._export_bet_checklist(
                int(round_id), mode=mode, banker_name=banker, rake_percent=rake
            )

        self._open_settle_mode_dialog(
            round_id=int(round_id),
            title="选择结算模式",
            confirm_text="生成核对列表",
            ask_on_banker_short=False,
            on_confirm=_after_mode,
        )

    def _export_bet_checklist(
        self,
        round_id: int,
        mode: str = "no_banker",
        banker_name: str = "",
        rake_percent: float = 0.0,
    ) -> None:
        """按已选模式导出核对图；有庄余额不足不弹窗，图上备注协商余额不足。"""
        bets = self.store.list_bets(int(round_id), valid_only=False)
        if not bets:
            messagebox.showinfo("提示", "本局暂无下注玩家", parent=self)
            return

        rows = self._build_bet_checklist_rows(bets)
        fieldnames = [
            "序号",
            "用户账号 ID",
            "下注金额",
            "有效性",
            "无效说明",
        ]
        valid_rows = [r for r in rows if r.get("有效性") == "有效"]
        total_amount = round(
            sum(float(r.get("下注金额") or 0) for r in valid_rows), 2
        )
        bet_count = len(valid_rows)
        mode_label = "有庄" if mode == "banker" else "无庄"
        slogan = f"下注玩家核对列表｜金额 {total_amount:g}｜人数 {bet_count}｜{mode_label}"
        if mode == "banker" and banker_name:
            slogan += f"｜庄家 {banker_name}"

        tip_text = None
        if mode == "banker" and banker_name:
            ok, _detail = self._check_banker_balance(
                int(round_id), banker_name, rake_percent=rake_percent
            )
            if not ok:
                tip_text = "备注：余额不足"

        out_dir = Path(self.engine.report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime as _dt

        path = (
            out_dir
            / f"bet_check_{self.room_name}_{round_id}_{_dt.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        self.engine._export_table_image(
            path,
            rows,
            fieldnames,
            slogan=slogan,
            tip_text=tip_text,
        )

        try:
            desktop, clipped = self._save_report_to_desktop(str(path))
            clip_tip = (
                "\n已复制到剪贴板，可直接粘贴发送"
                if clipped
                else "\n（剪贴板复制失败，请手动打开桌面图片）"
            )
            messagebox.showinfo(
                "完成",
                f"核对列表已保存到桌面:\n{desktop}{clip_tip}",
                parent=self,
            )
            self.status_var.set(
                f"核对列表已存桌面{'并已复制剪贴板' if clipped else ''}: {desktop}"
            )
        except Exception as e:
            logger.exception("核对列表保存桌面失败")
            clipped = self._copy_image_to_clipboard(path)
            messagebox.showwarning(
                "保存桌面失败",
                f"已生成文件:\n{path}\n桌面复制失败: {e}"
                + ("\n已复制到剪贴板，可直接粘贴发送" if clipped else ""),
                parent=self,
            )
            self.status_var.set(f"核对列表: {path}")

    def _void_current_round(self) -> None:
        """手动作废本局：所有下注不计入；下注未预扣余额故无需额外返还。"""
        rnd = self._current_review_round()
        if not rnd:
            messagebox.showinfo("提示", "没有可作废的对局", parent=self)
            return
        round_id = int(rnd["id"])
        if not messagebox.askyesno(
            "确认作废",
            f"将局#{round_id} 标记为作废局？\n"
            "• 所有下注改为无效、不参与结算\n"
            "• 本局不可再抽水结算\n"
            "• 当前下注未预扣余额，作废后账户余额不变（等同返还）",
            parent=self,
        ):
            return
        try:
            self.store.void_round(round_id)
            self.refresh_all()
            messagebox.showinfo("完成", f"局#{round_id} 已作废", parent=self)
            self.status_var.set(f"局#{round_id} 已作废")
        except Exception as e:
            messagebox.showerror("失败", str(e), parent=self)

    def _rollback_last_settlement(self) -> None:
        """回退最近已结算局：恢复余额，局改回已结束，可重新上传红包图结算。"""
        if not self.room_name:
            messagebox.showwarning("提示", "请先填写群名称", parent=self)
            return
        rounds = self.store.list_rounds(self.room_name, limit=30)
        rnd = next((r for r in rounds if r.get("status") == "settled"), None)
        if not rnd:
            messagebox.showinfo("提示", "当前群没有已结算的对局可回退", parent=self)
            return
        round_id = int(rnd["id"])
        if not messagebox.askyesno(
            "确认回退结算",
            f"回退局#{round_id} 的结算？\n"
            "• 按本局流水净变动恢复各用户余额\n"
            "• 清除本局结算明细\n"
            "• 局状态改回「已结束」，可重新上传红包截图结算\n"
            "• 下注记录保留不变",
            parent=self,
        ):
            return
        try:
            out = self.store.rollback_settled_round(round_id)
            n = int(out.get("_rollback_players") or 0)
            self.refresh_all()
            messagebox.showinfo(
                "完成",
                f"局#{round_id} 已回退\n已恢复 {n} 名用户余额\n请重新点击「结算本局」上传截图",
                parent=self,
            )
            self.status_var.set(f"局#{round_id} 结算已回退，可重新结算")
        except Exception as e:
            messagebox.showerror("回退失败", str(e), parent=self)

    def _pick_round_for_settle(self) -> Optional[Dict[str, Any]]:
        if not self.room_name:
            messagebox.showwarning("提示", "请先填写群名称", parent=self)
            return None
        active = self.store.get_active_round(self.room_name)
        if active:
            if messagebox.askyesno(
                "提示",
                f"局#{active['id']} 仍在收集中，是否先结束并结算？",
                parent=self,
            ):
                return self.store.end_round(self.room_name)
            return None
        ended = self.store.get_latest_ended_round(self.room_name)
        if not ended:
            messagebox.showinfo("提示", "没有可结算的对局", parent=self)
            return None
        if ended.get("status") == "settled":
            messagebox.showinfo("提示", f"最近一局#{ended['id']} 已结算", parent=self)
            return None
        if ended.get("status") == "voided":
            messagebox.showinfo("提示", f"最近一局#{ended['id']} 已作废", parent=self)
            return None
        return ended

    def _open_settle_mode_dialog(
        self,
        round_id: int,
        *,
        title: str = "选择结算模式",
        confirm_text: str = "下一步：上传红包截图",
        ask_on_banker_short: bool = True,
        on_confirm: Optional[Callable[[str, str, float], None]] = None,
    ) -> None:
        """共用：选择无庄/有庄与抽水；有庄可校验余额（核对列表可不弹确认）。"""
        mode_win = tk.Toplevel(self)
        mode_win.title(title)
        mode_win.configure(bg=UI["bg"])
        mode_win.transient(self)
        mode_win.resizable(True, True)
        mode_win.minsize(600, 400)
        self._center_window(mode_win, 650, 420)
        mode_win.grab_set()
        mode_win.focus_force()
        mode_win.lift()

        foot = ttk.Frame(mode_win, padding=(20, 14))
        foot.pack(side=tk.BOTTOM, fill=tk.X)

        body = ttk.Frame(mode_win, padding=(24, 20))
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        mode_var = tk.StringVar(value="no_banker")
        ttk.Label(body, text="请选择本局结算模式", style="Section.TLabel").pack(
            anchor=tk.W, pady=(0, 10)
        )

        rake_var = tk.StringVar(value="5")
        rake_row = ttk.Frame(body)
        rake_row.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(rake_row, text="抽水比例(%)").pack(side=tk.LEFT)
        ttk.Entry(rake_row, textvariable=rake_var, width=12).pack(side=tk.LEFT, padx=10)

        ttk.Radiobutton(
            body, text="无庄模式", variable=mode_var, value="no_banker"
        ).pack(anchor=tk.W, pady=8)

        ttk.Radiobutton(
            body, text="有庄模式", variable=mode_var, value="banker"
        ).pack(anchor=tk.W, pady=8)
        banker_var = tk.StringVar()
        banker_row = ttk.Frame(body)
        ttk.Label(banker_row, text="庄家名称").pack(side=tk.LEFT)
        ttk.Entry(banker_row, textvariable=banker_var, width=24).pack(side=tk.LEFT, padx=10)

        def _sync_banker_row(*_args):
            if mode_var.get() == "banker":
                if not banker_row.winfo_ismapped():
                    banker_row.pack(fill=tk.X, padx=28, pady=(0, 4))
            else:
                banker_row.pack_forget()

        mode_var.trace_add("write", _sync_banker_row)
        _sync_banker_row()

        def do_next():
            mode = mode_var.get()
            banker = ""
            try:
                rake = float(rake_var.get().strip() or "0")
            except ValueError:
                messagebox.showerror("错误", "抽水比例必须是数字", parent=mode_win)
                return
            if rake < 0:
                messagebox.showerror("错误", "抽水比例不能为负", parent=mode_win)
                return
            if mode == "banker":
                banker = banker_var.get().strip()
                if not banker:
                    messagebox.showerror("错误", "请填写庄家名称", parent=mode_win)
                    return
                if ask_on_banker_short:
                    ok, detail = self._check_banker_balance(
                        int(round_id), banker, rake_percent=rake
                    )
                    if not ok:
                        if not messagebox.askyesno(
                            "庄家余额不足",
                            f"{detail}\n\n余额不足当庄，仍要继续？",
                            parent=mode_win,
                        ):
                            return
            mode_win.destroy()
            if on_confirm:
                on_confirm(mode, banker, rake)

        ttk.Button(foot, text="取消", command=mode_win.destroy, style="Ghost.TButton").pack(
            side=tk.RIGHT, padx=6
        )
        ttk.Button(
            foot, text=confirm_text, command=do_next, style="Primary.TButton"
        ).pack(side=tk.RIGHT, padx=6)

    def _on_settle(self) -> None:
        rnd = self._pick_round_for_settle()
        if not rnd:
            return

        self._open_settle_mode_dialog(
            round_id=int(rnd["id"]),
            title="选择结算模式",
            confirm_text="下一步：上传红包截图",
            on_confirm=lambda mode, banker, rake: self._settle_with_images(
                int(rnd["id"]), mode, banker, rake
            ),
        )

    def _round_valid_bet_total(self, round_id: int) -> float:
        """当局有效下注总额（全输时庄家需赔付的上限）。"""
        bets = self.store.list_bets(int(round_id), valid_only=False)
        return round(
            sum(
                float(b.get("amount") or 0)
                for b in bets
                if bool(b.get("is_valid"))
            ),
            2,
        )

    def _resolve_player_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """按昵称/备注编号解析余额账户。"""
        from omni_bot_sdk.game.settlement import _norm_name, _remark_match_key

        name = (name or "").strip()
        if not name or not self.room_name:
            return None
        player = self.store.get_player(name, self.room_name)
        if player:
            return player
        key = _remark_match_key(name) or _norm_name(name)
        if not key:
            return None
        for p in self.store.list_players(self.room_name):
            nick = str(p.get("nickname") or "")
            if _remark_match_key(nick) == key or _norm_name(nick) == key:
                return p
        return None

    def _check_banker_balance(
        self, round_id: int, banker_name: str, rake_percent: float = 0.0
    ) -> tuple:
        """
        校验庄家余额是否够扛：全输赔付 + 额外抽水。
        例：押注10000、抽5% → 全输赔10000，另扣抽水500，需备≥10500。
        抽水不从押注里减，只额外扣庄家余额。
        返回 (是否足够, 说明文案)。
        """
        total = self._round_valid_bet_total(round_id)
        rake = round(total * float(rake_percent or 0) / 100.0, 2)
        need = round(total + rake, 2)
        player = self._resolve_player_by_name(banker_name)
        if not player:
            return False, f"庄家未在用户表维护: {banker_name}"
        bal = round(float(player.get("balance") or 0), 2)
        nick = str(player.get("nickname") or banker_name)
        detail = (
            f"有效总下注 {total:g}\n"
            f"全输需赔 {total:g}"
            + (f"\n抽水另扣 {rake:g}（{float(rake_percent):g}%，不从押注减）" if rake else "")
            + f"\n建议备款 ≥ {need:g}\n庄家 {nick} 当前余额 {bal:g}"
        )
        if bal + 1e-9 < need:
            return False, detail + "\n→ 余额不足（全输赔付+抽水），不建议当庄"
        return True, detail

    def _settle_with_images(
        self, round_id: int, mode: str, banker_name: str, rake_percent: float
    ) -> None:
        paths = filedialog.askopenfilenames(
            parent=self,
            title="选择红包领取详情截图（可多选）",
            filetypes=[
                ("图片", "*.png *.jpg *.jpeg *.bmp *.webp"),
                ("全部", "*.*"),
            ],
        )
        if not paths:
            return

        self.status_var.set(f"正在识别 {len(paths)} 张截图...")
        self.update_idletasks()

        def worker():
            try:
                claims = self.ocr.parse_images(list(paths))
                bets = self.store.list_bets(round_id, valid_only=False)
                rows = self.engine.build_player_rows(
                    bets,
                    claims,
                    self.room_name,
                    banker_name=banker_name if mode == "banker" else "",
                    include_invalid=True,
                )
                if mode == "banker":
                    result_rows, summary = self.engine.settle_with_banker(
                        rows,
                        banker_name,
                        claims=claims,
                        room_name=self.room_name,
                        rake_percent=rake_percent,
                    )
                else:
                    result_rows, summary = self.engine.settle_no_banker(
                        rows,
                        rake_percent,
                    )
                warns = summary.get("warnings") or []
                if warns:
                    logger.warning("结算告警: %s", warns)

                def confirm_apply():
                    def _preview_line(r):
                        bet_txt = (
                            "庄家"
                            if r.get("is_banker") or r.get("bet_amount") == "庄家"
                            else f"押{r['bet_amount']}"
                        )
                        return (
                            f"{r['seq']}. {r['nickname']} {bet_txt} "
                            f"点{r['point']} 加减{float(r['delta']):+.2f}"
                        )

                    preview = "\n".join(_preview_line(r) for r in result_rows[:30])
                    if len(result_rows) > 30:
                        preview += f"\n...共{len(result_rows)}人"
                    summary_text = (
                        f"模式={summary.get('mode')} 总下注={summary.get('total_bet')} "
                        f"抽水={summary.get('rake_amount')} 奖金池={summary.get('pool_amount')}\n"
                        f"识别领取 {len(claims)} 条\n\n{preview}\n\n确认写入余额？"
                    )
                    if not messagebox.askyesno("确认结算", summary_text, parent=self):
                        self.status_var.set("已取消结算")
                        return
                    report = self.engine.apply_and_save(
                        round_id, self.room_name, result_rows, summary
                    )
                    self.refresh_all()
                    try:
                        desktop_path, clipped = self._save_report_to_desktop(report)
                        clip_tip = (
                            "\n已复制到剪贴板，可直接粘贴发送"
                            if clipped
                            else "\n（剪贴板复制失败，请手动打开桌面图片）"
                        )
                        messagebox.showinfo(
                            "完成",
                            f"结算完成\n结算图已保存到桌面:\n{desktop_path}{clip_tip}",
                            parent=self,
                        )
                        self.status_var.set(
                            f"结算图已存桌面{'并已复制剪贴板' if clipped else ''}: {desktop_path}"
                        )
                    except Exception as e:
                        logger.exception("保存结算图到桌面失败")
                        clipped = self._copy_image_to_clipboard(report)
                        messagebox.showwarning(
                            "完成（桌面保存失败）",
                            f"结算已写入\n本地报表: {report}\n"
                            f"保存到桌面失败: {e}"
                            + ("\n已复制到剪贴板，可直接粘贴发送" if clipped else ""),
                            parent=self,
                        )
                        self.status_var.set(f"结算完成: {report}")

                self.after(0, confirm_apply)
            except Exception as e:
                # 必须把 e 绑进默认参数：except 结束后局部 e 会被清除，
                # after 回调再取 e 会 NameError，界面表现为「上传后没反应」
                logger.exception("结算失败")
                err_msg = str(e) or e.__class__.__name__

                def _show_settle_error(msg: str = err_msg) -> None:
                    messagebox.showerror("结算失败", msg, parent=self)
                    self.status_var.set(f"结算失败: {msg}")

                self.after(0, _show_settle_error)

        threading.Thread(target=worker, daemon=True).start()

    def _schedule_send_report(
        self, report_path: str, room_name: str, delay_sec: int = 5
    ) -> None:
        """「已提交发送」弹窗关闭后，再延迟操作客户端发群。"""
        remaining = [max(1, int(delay_sec))]

        def tick() -> None:
            left = remaining[0]
            if left > 0:
                self.status_var.set(
                    f"已提交发群，{left} 秒后操作客户端发送，请勿操作微信"
                )
                remaining[0] = left - 1
                self.after(1000, tick)
                return
            self.status_var.set(f"正在发送结算表到群：{room_name}…")
            try:
                if self.send_file_callback:
                    self.send_file_callback(report_path, room_name)
                self.status_var.set(f"结算表已交由客户端发送：{room_name}")
            except Exception as e:
                logger.exception("自动发送结算表失败")
                self.status_var.set(f"自动发群失败: {e}")
                messagebox.showerror(
                    "发群失败", f"发送结算表失败:\n{e}", parent=self
                )

        tick()


_gui_thread: Optional[threading.Thread] = None
_gui_app: Optional[GameAdminApp] = None


def start_game_gui(
    store: GameStore,
    room_name: str = "",
    ocr_processor=None,
    report_dir: str = "game_records",
    min_bet: float = 50,
    send_file_callback: Optional[Callable[[str, str], None]] = None,
) -> None:
    """在后台线程启动 GUI（Windows 下可用）。"""
    global _gui_thread, _gui_app

    if _gui_thread and _gui_thread.is_alive():
        logger.info("游戏 GUI 已在运行")
        return

    def runner():
        global _gui_app
        try:
            _gui_app = GameAdminApp(
                store=store,
                room_name=room_name,
                ocr_processor=ocr_processor,
                report_dir=report_dir,
                min_bet=min_bet,
                send_file_callback=send_file_callback,
            )
            _gui_app.mainloop()
        except Exception:
            logger.exception("游戏 GUI 异常退出")

    _gui_thread = threading.Thread(target=runner, name="GameAdminGUI", daemon=True)
    _gui_thread.start()
    logger.info("游戏后台 GUI 已启动")
