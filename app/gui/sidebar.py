from __future__ import annotations

import customtkinter as ctk

from app.gui.theme import MUTED, PRIMARY, PRIMARY_HOVER, PRIMARY_SOFT, TEXT, font
from app.version import APP_NAME


NAV_ITEMS = [
    ("analysis", "分析任务"),
    ("history", "历史记录"),
    ("export", "数据导出"),
    ("settings", "系统设置"),
    ("about", "关于"),
]


class Sidebar(ctk.CTkFrame):
    def __init__(self, master, on_select, **kwargs):
        super().__init__(master, width=188, fg_color="#0F766E", corner_radius=0, **kwargs)
        self.on_select = on_select
        self.pack_propagate(False)
        ctk.CTkLabel(self, text=APP_NAME, font=font(15, "bold"), text_color="#ECFDF5", wraplength=160, justify="left").pack(fill="x", padx=16, pady=(22, 18))
        self.buttons: dict[str, ctk.CTkButton] = {}
        for key, label in NAV_ITEMS:
            btn = ctk.CTkButton(
                self,
                text=label,
                anchor="w",
                fg_color="transparent",
                hover_color=PRIMARY_HOVER,
                text_color="#ECFDF5",
                font=font(14),
                command=lambda k=key: self.select(k),
            )
            btn.pack(fill="x", padx=10, pady=3)
            self.buttons[key] = btn
        ctk.CTkLabel(self, text="独立 Key 限流  ·  API First", font=font(11), text_color="#99F6E4").pack(side="bottom", pady=16)
        self.highlight("analysis")

    def highlight(self, key: str) -> None:
        for item, btn in self.buttons.items():
            btn.configure(fg_color=PRIMARY_HOVER if item == key else "transparent")

    def select(self, key: str) -> None:
        self.highlight(key)
        self.on_select(key)
