#!/usr/bin/env python
"""客户用：查看本机机器码（可打包为 exe）。"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from machine_util import get_machine_code


def main() -> None:
    root = tk.Tk()
    root.title("查看机器码")
    root.resizable(False, False)
    root.minsize(520, 200)

    frm = ttk.Frame(root, padding=16)
    frm.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frm, text="请将本机机器码发给发卡方，用于绑定激活码。").pack(anchor=tk.W)

    code_var = tk.StringVar()
    entry = ttk.Entry(frm, textvariable=code_var, width=56, font=("Consolas", 11))
    entry.pack(fill=tk.X, pady=(12, 8))

    tip = tk.StringVar(value="")
    ttk.Label(frm, textvariable=tip, foreground="#666").pack(anchor=tk.W)

    def refresh() -> None:
        try:
            code = get_machine_code()
            code_var.set(code)
            tip.set("已刷新")
        except Exception as e:
            code_var.set("")
            tip.set("")
            messagebox.showerror("错误", f"获取机器码失败:\n{e}", parent=root)

    def copy_code() -> None:
        code = code_var.get().strip()
        if not code:
            messagebox.showwarning("提示", "没有可复制的机器码", parent=root)
            return
        root.clipboard_clear()
        root.clipboard_append(code)
        tip.set("已复制到剪贴板")

    btns = ttk.Frame(frm)
    btns.pack(fill=tk.X, pady=(12, 0))
    ttk.Button(btns, text="刷新", command=refresh).pack(side=tk.LEFT)
    ttk.Button(btns, text="复制机器码", command=copy_code).pack(side=tk.LEFT, padx=8)

    refresh()
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 3
    root.geometry(f"+{x}+{y}")
    root.mainloop()


if __name__ == "__main__":
    main()
