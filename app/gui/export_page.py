from __future__ import annotations

import os
from tkinter import filedialog, messagebox

import customtkinter as ctk

from app.gui.theme import BG, MUTED, PANEL, TEXT, font
from app.utils.paths import OUTPUT_DIR, REPORT_DIR


class ExportPage(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self.app = app
        card = ctk.CTkFrame(self, fg_color=PANEL)
        card.pack(fill="both", expand=True, padx=24, pady=24)
        ctk.CTkLabel(card, text="数据导出", font=font(20, "bold"), text_color=TEXT, anchor="w").pack(fill="x", padx=20, pady=(18, 6))
        ctk.CTkLabel(card, text="Excel 保存在 output/，JSON 保存在 output/reports/，原始 API 在 data/raw/。", font=font(13), text_color=MUTED, anchor="w").pack(fill="x", padx=20)
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(anchor="w", padx=20, pady=16)
        ctk.CTkButton(btns, text="打开 Excel 目录", command=lambda: self._open(OUTPUT_DIR)).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="打开 JSON 目录", fg_color="#E5E7EB", text_color=TEXT, command=lambda: self._open(REPORT_DIR)).pack(side="left", padx=6)
        last = ctk.CTkButton(btns, text="打开最近一次 Excel", command=self._open_last)
        last.pack(side="left", padx=6)

    def _open(self, path) -> None:
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def _open_last(self) -> None:
        files = sorted(OUTPUT_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            messagebox.showinfo("没有文件", "还没有生成过 Excel")
            return
        os.startfile(files[0])
