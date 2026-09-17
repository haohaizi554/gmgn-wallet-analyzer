from __future__ import annotations

import customtkinter as ctk

from app.gui.theme import MUTED, PANEL, PRIMARY, TEXT, font


class ProgressPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=PANEL, **kwargs)
        self.stage = ctk.CTkLabel(self, text="等待开始", font=font(13, "bold"), text_color=TEXT, anchor="w")
        self.stage.pack(fill="x", padx=10, pady=(10, 0))
        self.detail = ctk.CTkLabel(self, text="当前钱包：-    当前 Token：-", font=font(12), text_color=MUTED, anchor="w")
        self.detail.pack(fill="x", padx=10, pady=(2, 0))
        self.api_label = ctk.CTkLabel(self, text="API 正常", font=font(12), text_color=PRIMARY, anchor="w")
        self.api_label.pack(fill="x", padx=10, pady=(2, 0))
        self.bar = ctk.CTkProgressBar(self, height=8)
        self.bar.pack(fill="x", padx=10, pady=(8, 12))
        self.bar.set(0)
        self.count = ctk.CTkLabel(self, text="0 / 0", font=font(12), text_color=MUTED, anchor="e")
        self.count.pack(fill="x", padx=10, pady=(0, 10))

    def update_progress(self, message: str, done: int, total: int, wallet: str = "", token: str = "", api: str = "") -> None:
        self.stage.configure(text=message or "分析中")
        self.detail.configure(text=f"当前钱包：{wallet or '-'}    当前 Token：{token or '-'}")
        if api:
            self.api_label.configure(text=api)
        self.count.configure(text=f"{done} / {total}" if total else "准备中")
        if total:
            self.bar.set(min(1.0, done / total))
        else:
            self.bar.set(0)

    def reset(self) -> None:
        self.update_progress("等待开始", 0, 0)
        self.bar.set(0)
