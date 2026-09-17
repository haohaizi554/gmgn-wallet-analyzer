from __future__ import annotations

import customtkinter as ctk

from app.gui.theme import BG, MUTED, PANEL, TEXT, font


class StatCard(ctk.CTkFrame):
    def __init__(self, master, title: str, value: str = "—", **kwargs):
        super().__init__(master, fg_color=PANEL, corner_radius=10, border_width=1, border_color="#E5E7EB", **kwargs)
        self.title_label = ctk.CTkLabel(self, text=title, text_color=MUTED, font=font(12), anchor="w")
        self.title_label.pack(fill="x", padx=12, pady=(10, 0))
        self.value_label = ctk.CTkLabel(self, text=value, text_color=TEXT, font=font(18, "bold"), anchor="w")
        self.value_label.pack(fill="x", padx=12, pady=(4, 12))

    def set_value(self, value: str) -> None:
        self.value_label.configure(text=value or "—")
