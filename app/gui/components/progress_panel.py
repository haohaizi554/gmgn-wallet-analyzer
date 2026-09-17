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
        self.meta = ctk.CTkLabel(self, text="Keys：-    数据源：等待任务", font=font(11), text_color=MUTED, anchor="w")
        self.meta.pack(fill="x", padx=10, pady=(2, 0))
        self.bar = ctk.CTkProgressBar(self, height=8)
        self.bar.pack(fill="x", padx=10, pady=(8, 12))
        self.bar.set(0)
        self.count = ctk.CTkLabel(self, text="0 / 0", font=font(12), text_color=MUTED, anchor="e")
        self.count.pack(fill="x", padx=10, pady=(0, 10))
        self._keys = "Keys：-"
        self._sources = "数据源：等待任务"
        self._last_progress: tuple | None = None
        self._last_api = "API 正常"

    def update_progress(self, message: str, done: int, total: int, wallet: str = "", token: str = "", api: str = "") -> None:
        key = (message or "分析中", int(done), int(total), wallet or "-", token or "-", api or "")
        if key == self._last_progress:
            return
        self._last_progress = key
        self.stage.configure(text=key[0])
        self.detail.configure(text=f"当前钱包：{key[3]}    当前 Token：{key[4]}")
        if api and api != self._last_api:
            self.api_label.configure(text=api)
            self._last_api = api
        count = f"{done} / {total}" if total else "准备中"
        if self.count.cget("text") != count:
            self.count.configure(text=count)
        self.bar.set(min(1.0, done / total) if total else 0)

    def set_api(self, text: str) -> None:
        text = text or "API 正常"
        if text == self._last_api:
            return
        self._last_api = text
        self.api_label.configure(text=text)

    def set_keys(self, text: str) -> None:
        text = text or "Keys：-"
        if text == self._keys:
            return
        self._keys = text
        self._refresh_meta()

    def set_sources(self, text: str) -> None:
        text = text or "数据源：等待任务"
        if text == self._sources:
            return
        self._sources = text
        self._refresh_meta()

    def _refresh_meta(self) -> None:
        self.meta.configure(text=f"{self._keys}    {self._sources}")

    def reset(self) -> None:
        self._last_progress = None
        self.update_progress("等待开始", 0, 0)
        self.set_keys("Keys：-")
        self.set_sources("数据源：等待任务")
        self.set_api("API 正常")
        self.bar.set(0)
