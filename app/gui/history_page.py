from __future__ import annotations

from tkinter import messagebox
import os

import customtkinter as ctk

from app.gui.theme import BG, MUTED, PANEL, TEXT, font
from app.utils.validators import short_address


class HistoryPage(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self.app = app
        ctk.CTkLabel(self, text="历史记录", font=font(20, "bold"), text_color=TEXT, anchor="w").pack(fill="x", padx=20, pady=(20, 8))
        ctk.CTkLabel(self, text="本地 SQLite 保存的分析报告，可打开 Excel / JSON。", font=font(13), text_color=MUTED, anchor="w").pack(fill="x", padx=20)
        self.listbox = ctk.CTkScrollableFrame(self, fg_color=PANEL)
        self.listbox.pack(fill="both", expand=True, padx=20, pady=16)
        self.refresh()

    def refresh(self) -> None:
        for child in self.listbox.winfo_children():
            child.destroy()
        rows = self.app.db_repos.list_jobs(40)
        reports = self.app.db_repos.list_reports(40)
        if not rows and not reports:
            ctk.CTkLabel(self.listbox, text="暂无历史报告", text_color=MUTED, font=font(14)).pack(pady=30)
            return
        header = ctk.CTkFrame(self.listbox, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=4)
        for col, w in [("时间", 160), ("Job / 钱包", 180), ("类型", 70), ("状态", 90), ("Token", 70), ("操作", 200)]:
            ctk.CTkLabel(header, text=col, width=w, anchor="w", font=font(12, "bold")).pack(side="left")
        from datetime import datetime

        for row in rows:
            frame = ctk.CTkFrame(self.listbox, fg_color="#F9FAFB")
            frame.pack(fill="x", padx=8, pady=3)
            created = datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M:%S") if row.get("created_at") else "-"
            summary = row.get("summary") or {}
            wallets = row.get("wallets") or []
            label = f"{row['job_id'][:8]} / {len(wallets)}钱包"
            ctk.CTkLabel(frame, text=created, width=160, anchor="w", font=font(12)).pack(side="left")
            ctk.CTkLabel(frame, text=label, width=180, anchor="w", font=font(12)).pack(side="left")
            ctk.CTkLabel(frame, text="单钱包" if row.get("job_type") == "single" else "批量", width=70, anchor="w", font=font(12)).pack(side="left")
            ctk.CTkLabel(frame, text=str(row.get("status") or "-"), width=90, anchor="w", font=font(12)).pack(side="left")
            ctk.CTkLabel(frame, text=str(summary.get("token_count", "-")), width=70, anchor="w", font=font(12)).pack(side="left")
            excel = row.get("excel_path") or summary.get("excel_path") or ""
            ctk.CTkButton(frame, text="打开 Excel", width=90, height=26, command=lambda p=excel: self._open(p)).pack(side="left", padx=4)

        for row in reports:
            frame = ctk.CTkFrame(self.listbox, fg_color="#FFFFFF")
            frame.pack(fill="x", padx=8, pady=3)
            created = datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M:%S") if row.get("created_at") else "-"
            summary = row.get("summary") or {}
            ctk.CTkLabel(frame, text=created, width=160, anchor="w", font=font(12)).pack(side="left")
            ctk.CTkLabel(frame, text=short_address(row["wallet_address"]), width=180, anchor="w", font=font(12)).pack(side="left")
            ctk.CTkLabel(frame, text=str(row.get("period") or "-"), width=70, anchor="w", font=font(12)).pack(side="left")
            ctk.CTkLabel(frame, text=str(row.get("status") or "-"), width=90, anchor="w", font=font(12)).pack(side="left")
            ctk.CTkLabel(frame, text=str(summary.get("token_count", "-")), width=70, anchor="w", font=font(12)).pack(side="left")
            excel = row.get("excel_path") or ""
            json_path = row.get("json_path") or ""
            ctk.CTkButton(frame, text="打开 Excel", width=90, height=26, command=lambda p=excel: self._open(p)).pack(side="left", padx=4)
            ctk.CTkButton(frame, text="打开 JSON", width=90, height=26, fg_color="#E5E7EB", text_color=TEXT, command=lambda p=json_path: self._open(p)).pack(side="left")

    def _open(self, path: str) -> None:
        if not path or not os.path.exists(path):
            messagebox.showwarning("文件不存在", path or "空路径")
            return
        os.startfile(path)
