from __future__ import annotations

import customtkinter as ctk

from app.gui.theme import PRIMARY_HOVER, font


NAV_ITEMS = [
    ("analysis", "分析任务"),
    ("history", "历史记录"),
    ("viz", "数据可视化"),
    ("settings", "系统设置"),
    ("about", "关于"),
]


class Sidebar(ctk.CTkFrame):
    def __init__(self, master, on_select, **kwargs):
        super().__init__(master, width=124, fg_color="#0F766E", corner_radius=0, **kwargs)
        self.on_select = on_select
        self.pack_propagate(False)
        self.buttons: dict[str, ctk.CTkButton] = {}
        for idx, (key, label) in enumerate(NAV_ITEMS):
            btn = ctk.CTkButton(
                self,
                text=label,
                anchor="w",
                height=36,
                fg_color="transparent",
                hover_color=PRIMARY_HOVER,
                text_color="#ECFDF5",
                font=font(13),
                command=lambda k=key: self.select(k),
            )
            btn.pack(fill="x", padx=6, pady=(8, 2) if idx == 0 else 2)
            self.buttons[key] = btn
        ctk.CTkLabel(
            self,
            text="多数据源\n链上可验证",
            font=font(10),
            text_color="#99F6E4",
            justify="center",
        ).pack(side="bottom", pady=12)
        self.highlight("analysis")

    def highlight(self, key: str) -> None:
        if getattr(self, "_current", None) == key:
            return
        self._current = key
        for item, btn in self.buttons.items():
            btn.configure(fg_color=PRIMARY_HOVER if item == key else "transparent")

    def select(self, key: str) -> None:
        self.highlight(key)
        self.on_select(key)
