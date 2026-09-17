from __future__ import annotations

import customtkinter as ctk

PRIMARY = "#0F766E"
PRIMARY_HOVER = "#115E59"
PRIMARY_SOFT = "#CCFBF1"
BG = "#F3F4F6"
PANEL = "#FFFFFF"
TEXT = "#111827"
MUTED = "#6B7280"
BORDER = "#E5E7EB"
DANGER = "#B91C1C"
SUCCESS = "#15803D"
WARN = "#C2410C"

FONT_FAMILY = "Microsoft YaHei UI"


def apply_theme() -> None:
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("green")
    try:
        ctk.set_widget_scaling(1.0)
        ctk.set_window_scaling(1.0)
    except Exception:
        pass


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)
