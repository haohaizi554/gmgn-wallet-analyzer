from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from app.gui.theme import BORDER, MUTED, PANEL, TEXT, font


class OptionDrawer:
    """Dropdown trigger that opens an overlay panel. Does not expand in-place."""

    def __init__(self, master, title: str = "高级选项", summary: str = "", on_toggle: Optional[Callable[[bool], None]] = None):
        self.master = master
        self.title = title
        self.on_toggle = on_toggle
        self._popup: Optional[ctk.CTkToplevel] = None
        self._bind_id: Optional[str] = None
        self._summary = summary or "点击设置"
        self.trigger = ctk.CTkButton(
            master,
            text=self._trigger_text(),
            height=32,
            fg_color="#E5E7EB",
            hover_color="#D1D5DB",
            text_color=TEXT,
            font=font(13),
            anchor="w",
            command=self.toggle,
        )
        self.body: Optional[ctk.CTkFrame] = None

    def _trigger_text(self) -> str:
        return f"{self.title}    {self._summary}    ▾"

    def set_summary(self, text: str) -> None:
        self._summary = text or "点击设置"
        if self.trigger.winfo_exists():
            self.trigger.configure(text=self._trigger_text())

    def is_open(self) -> bool:
        return bool(self._popup is not None and self._popup.winfo_exists() and self._popup.state() != "withdrawn")

    def toggle(self) -> None:
        if self.is_open():
            self.close()
        else:
            self.open()

    def open(self) -> None:
        popup = self._ensure_popup()
        self.trigger.update_idletasks()
        x = self.trigger.winfo_rootx()
        y = self.trigger.winfo_rooty() + self.trigger.winfo_height() + 2
        width = max(self.trigger.winfo_width(), 280)
        popup.update_idletasks()
        height = max(popup.winfo_reqheight(), 240)
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.deiconify()
        popup.lift()
        popup.focus_force()
        root = self.trigger.winfo_toplevel()
        if self._bind_id is None:
            self._bind_id = root.bind("<Button-1>", self._on_root_click, add="+")
        if self.on_toggle:
            self.on_toggle(True)

    def close(self) -> None:
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.withdraw()
        root = self.trigger.winfo_toplevel()
        if self._bind_id is not None:
            try:
                root.unbind("<Button-1>", self._bind_id)
            except Exception:
                pass
            self._bind_id = None
        if self.on_toggle:
            self.on_toggle(False)

    def _ensure_popup(self) -> ctk.CTkToplevel:
        if self._popup is not None and self._popup.winfo_exists():
            return self._popup
        popup = ctk.CTkToplevel(self.trigger)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.configure(fg_color=PANEL)
        try:
            popup.attributes("-topmost", True)
        except Exception:
            pass
        shell = ctk.CTkFrame(popup, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=8)
        shell.pack(fill="both", expand=True)
        head = ctk.CTkFrame(shell, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(8, 0))
        ctk.CTkLabel(head, text=self.title, font=font(13, "bold"), text_color=TEXT, anchor="w").pack(side="left")
        ctk.CTkButton(head, text="关闭", width=52, height=24, fg_color="#E5E7EB", text_color=TEXT, command=self.close).pack(side="right")
        self.body = ctk.CTkFrame(shell, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        popup.bind("<Escape>", lambda _e: self.close())
        self._popup = popup
        return popup

    def _on_root_click(self, event) -> None:
        if not self.is_open() or self._popup is None:
            return
        widget = event.widget
        try:
            if str(widget).startswith(str(self._popup)):
                return
            if str(widget).startswith(str(self.trigger)):
                return
        except Exception:
            pass
        px, py = self._popup.winfo_rootx(), self._popup.winfo_rooty()
        pw, ph = self._popup.winfo_width(), self._popup.winfo_height()
        if px <= event.x_root <= px + pw and py <= event.y_root <= py + ph:
            return
        tx, ty = self.trigger.winfo_rootx(), self.trigger.winfo_rooty()
        tw, th = self.trigger.winfo_width(), self.trigger.winfo_height()
        if tx <= event.x_root <= tx + tw and ty <= event.y_root <= ty + th:
            return
        self.close()
