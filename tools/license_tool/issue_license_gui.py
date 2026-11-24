#!/usr/bin/env python
"""发卡方用：根据机器码 + 过期日生成激活码（可打包为 exe）。"""

from __future__ import annotations

import sys
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from issue_license import default_private_key_path, issue


def main() -> None:
    root = tk.Tk()
    root.title("生成激活码")
    root.resizable(False, False)
    root.minsize(640, 420)

    frm = ttk.Frame(root, padding=16)
    frm.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        frm,
        text="输入客户机器码与过期日（YYYY-MM-DD），生成绑定该机器的激活码。",
    ).pack(anchor=tk.W)

    mid_var = tk.StringVar()
    exp_var = tk.StringVar(
        value=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    )
    sn_var = tk.StringVar()
    key_path_var = tk.StringVar(value=str(default_private_key_path()))
    tip_var = tk.StringVar(value="")

    grid = ttk.Frame(frm)
    grid.pack(fill=tk.X, pady=(12, 0))

    ttk.Label(grid, text="机器码").grid(row=0, column=0, sticky=tk.W, pady=4)
    ttk.Entry(grid, textvariable=mid_var, width=58).grid(
        row=0, column=1, sticky=tk.EW, padx=(8, 0), pady=4
    )

    ttk.Label(grid, text="过期日").grid(row=1, column=0, sticky=tk.W, pady=4)
    ttk.Entry(grid, textvariable=exp_var, width=20).grid(
        row=1, column=1, sticky=tk.W, padx=(8, 0), pady=4
    )

    ttk.Label(grid, text="流水号").grid(row=2, column=0, sticky=tk.W, pady=4)
    ttk.Entry(grid, textvariable=sn_var, width=24).grid(
        row=2, column=1, sticky=tk.W, padx=(8, 0), pady=4
    )
    ttk.Label(grid, text="可空，默认随机").grid(row=2, column=1, sticky=tk.E, pady=4)

    ttk.Label(grid, text="私钥文件").grid(row=3, column=0, sticky=tk.W, pady=4)
    key_row = ttk.Frame(grid)
    key_row.grid(row=3, column=1, sticky=tk.EW, padx=(8, 0), pady=4)
    ttk.Entry(key_row, textvariable=key_path_var).pack(
        side=tk.LEFT, fill=tk.X, expand=True
    )

    def browse_key() -> None:
        path = filedialog.askopenfilename(
            parent=root,
            title="选择 private_key.pem",
            filetypes=[("PEM", "*.pem"), ("全部", "*.*")],
        )
        if path:
            key_path_var.set(path)

    ttk.Button(key_row, text="浏览…", command=browse_key).pack(side=tk.LEFT, padx=(8, 0))
    grid.columnconfigure(1, weight=1)

    ttk.Label(frm, text="激活码").pack(anchor=tk.W, pady=(16, 4))
    out = tk.Text(frm, height=8, width=72, wrap=tk.WORD, font=("Consolas", 10))
    out.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frm, textvariable=tip_var, foreground="#666").pack(anchor=tk.W, pady=(6, 0))

    def generate() -> None:
        mid = mid_var.get().strip()
        exp = exp_var.get().strip()
        sn = sn_var.get().strip()
        key_path = Path(key_path_var.get().strip())
        if not mid:
            messagebox.showwarning("提示", "请填写机器码", parent=root)
            return
        try:
            token = issue(mid, exp, serial=sn, private_key_path=key_path)
        except Exception as e:
            messagebox.showerror("生成失败", str(e), parent=root)
            return
        out.delete("1.0", tk.END)
        out.insert("1.0", token)
        tip_var.set("已生成，可复制发给客户写入 config.yaml 的 license.key")

    def copy_out() -> None:
        token = out.get("1.0", tk.END).strip()
        if not token:
            messagebox.showwarning("提示", "请先生成激活码", parent=root)
            return
        root.clipboard_clear()
        root.clipboard_append(token)
        tip_var.set("激活码已复制到剪贴板")

    btns = ttk.Frame(frm)
    btns.pack(fill=tk.X, pady=(12, 0))
    ttk.Button(btns, text="生成激活码", command=generate).pack(side=tk.LEFT)
    ttk.Button(btns, text="复制激活码", command=copy_out).pack(side=tk.LEFT, padx=8)

    root.update_idletasks()
    w, h = max(root.winfo_width(), 660), max(root.winfo_height(), 440)
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 4
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.mainloop()


if __name__ == "__main__":
    main()
