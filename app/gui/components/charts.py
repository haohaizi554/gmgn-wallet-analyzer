from __future__ import annotations

import tkinter as tk
from typing import Iterable, Optional, Sequence

import customtkinter as ctk

from app.gui.theme import BORDER, MUTED, PANEL, PRIMARY, TEXT, font
from app.gui.viz_metrics import NamedCount, TokenPoint, format_signed_usd

UP = "#059669"
DOWN = "#DC2626"
FLAT = "#94A3B8"
GRID = "#E5E7EB"
PLOT = "#F8FAFC"


class ChartCard(ctk.CTkFrame):
    def __init__(self, master, title: str, height: int = 280, **kwargs):
        super().__init__(master, fg_color=PANEL, corner_radius=10, border_width=1, border_color=BORDER, **kwargs)
        ctk.CTkLabel(self, text=title, font=font(13, "bold"), text_color=TEXT, anchor="w").pack(fill="x", padx=14, pady=(12, 0))
        self.canvas = tk.Canvas(self, height=height, bg="#FFFFFF", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=8)
        self._empty = "暂无数据"
        self._job: str | None = None
        self._size = (0, 0)
        self.canvas.bind("<Configure>", self._on_resize)

    def _on_resize(self, event) -> None:
        if event.widget is not self.canvas:
            return
        if abs(event.width - self._size[0]) < 3 and abs(event.height - self._size[1]) < 3:
            return
        self._size = (event.width, event.height)
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(30, self.redraw)

    def set_empty(self, text: str) -> None:
        self._empty = text
        self.redraw()

    def redraw(self) -> None:
        self._job = None
        self.canvas.delete("all")
        w = max(int(self.canvas.winfo_width()), 40)
        h = max(int(self.canvas.winfo_height()), 40)
        if not self._has_data():
            self.canvas.create_text(w / 2, h / 2, text=self._empty, fill=MUTED, font=("Microsoft YaHei UI", 12))
            return
        self._paint(w, h)

    def _has_data(self) -> bool:
        return True

    def _paint(self, w: int, h: int) -> None:
        raise NotImplementedError


class SignedBarChart(ChartCard):
    def __init__(self, master, title: str = "盈亏贡献 Top 10", **kwargs):
        super().__init__(master, title, height=300, **kwargs)
        self.rows: list[tuple[str, float]] = []

    def set_tokens(self, tokens: Sequence[TokenPoint], limit: int = 10) -> None:
        ranked = sorted(tokens, key=lambda t: abs(t.realized), reverse=True)[:limit]
        ranked.sort(key=lambda t: t.realized, reverse=True)
        self.rows = [(t.symbol, t.realized) for t in ranked if t.realized]
        self.redraw()

    def _has_data(self) -> bool:
        return bool(self.rows)

    def _paint(self, w: int, h: int) -> None:
        left, right, top, bottom = 86, w - 58, 8, h - 18
        axis = left + (right - left) / 2
        max_abs = max(abs(v) for _, v in self.rows) or 1.0
        usable = (right - left) / 2
        n = len(self.rows)
        gap = 6
        bar_h = max(12, min(22, (bottom - top - gap * n) / max(n, 1)))
        self.canvas.create_line(axis, top, axis, bottom, fill=GRID)
        for i, (label, value) in enumerate(self.rows):
            y = top + i * (bar_h + gap)
            length = usable * (abs(value) / max_abs)
            color = UP if value > 0 else DOWN
            if value >= 0:
                x0, x1 = axis, axis + length
            else:
                x0, x1 = axis - length, axis
            self.canvas.create_rectangle(x0, y, x1, y + bar_h, fill=color, outline="")
            self.canvas.create_text(left - 8, y + bar_h / 2, text=label[:10], fill=TEXT, font=("Microsoft YaHei UI", 9), anchor="e")
            self.canvas.create_text(
                x1 + 6 if value >= 0 else x0 - 6,
                y + bar_h / 2,
                text=format_signed_usd(value),
                fill=color,
                font=("Consolas", 9),
                anchor="w" if value >= 0 else "e",
            )


class DonutChart(ChartCard):
    def __init__(self, master, title: str = "胜负结构", **kwargs):
        super().__init__(master, title, height=260, **kwargs)
        self.slices: list[tuple[str, float, str]] = []
        self.center = ""

    def set_outcome(self, win: int, loss: int, flat: int, win_rate: Optional[float]) -> None:
        self.slices = [
            ("盈利", float(win), UP),
            ("亏损", float(loss), DOWN),
            ("持平", float(flat), FLAT),
        ]
        self.center = f"{win_rate * 100:.0f}%" if win_rate is not None else "—"
        self.redraw()

    def _has_data(self) -> bool:
        return any(v > 0 for _, v, _ in self.slices)

    def _paint(self, w: int, h: int) -> None:
        size = min(w * 0.55, h - 16)
        cx, cy = w * 0.38, h / 2
        x0, y0 = cx - size / 2, cy - size / 2
        x1, y1 = cx + size / 2, cy + size / 2
        total = sum(v for _, v, _ in self.slices) or 1.0
        start = 90.0
        for label, value, color in self.slices:
            if value <= 0:
                continue
            extent = -360.0 * (value / total)
            self.canvas.create_arc(x0, y0, x1, y1, start=start, extent=extent, fill=color, outline="#FFFFFF", width=2)
            start += extent
        hole = size * 0.52
        self.canvas.create_oval(cx - hole / 2, cy - hole / 2, cx + hole / 2, cy + hole / 2, fill="#FFFFFF", outline="")
        self.canvas.create_text(cx, cy - 8, text=self.center, fill=TEXT, font=("Microsoft YaHei UI", 18, "bold"))
        self.canvas.create_text(cx, cy + 14, text="胜率", fill=MUTED, font=("Microsoft YaHei UI", 10))
        legend_x = w * 0.68
        legend_y = h / 2 - 36
        for i, (label, value, color) in enumerate(self.slices):
            y = legend_y + i * 28
            self.canvas.create_rectangle(legend_x, y, legend_x + 10, y + 10, fill=color, outline="")
            self.canvas.create_text(legend_x + 16, y + 4, text=f"{label}  {int(value)}", fill=TEXT, font=("Microsoft YaHei UI", 11), anchor="w")


class ComboChart(ChartCard):
    def __init__(self, master, title: str = "每日盈亏 / 累计", **kwargs):
        super().__init__(master, title, height=260, **kwargs)
        self.days: list[str] = []
        self.bars: list[float] = []
        self.line: list[float] = []

    def set_daily(self, days: Sequence[str], bars: Sequence[float], line: Sequence[float]) -> None:
        self.days = list(days)
        self.bars = list(bars)
        self.line = list(line)
        self.redraw()

    def _has_data(self) -> bool:
        return bool(self.days)

    def _paint(self, w: int, h: int) -> None:
        left, right, top, bottom = 52, w - 16, 12, h - 28
        values = list(self.bars) + list(self.line) + [0.0]
        lo, hi = min(values), max(values)
        if lo == hi:
            hi = lo + 1
            lo = lo - 1
        span = hi - lo
        n = len(self.days)
        slot = (right - left) / max(n, 1)
        bar_w = max(4, min(18, slot * 0.55))
        self.canvas.create_rectangle(left, top, right, bottom, fill=PLOT, outline=GRID)
        zero_y = bottom - (0 - lo) / span * (bottom - top)
        self.canvas.create_line(left, zero_y, right, zero_y, fill="#CBD5E1")
        pts = []
        for i, (bar, cum) in enumerate(zip(self.bars, self.line)):
            cx = left + slot * i + slot / 2
            y1 = bottom - (bar - lo) / span * (bottom - top)
            self.canvas.create_rectangle(cx - bar_w / 2, y1, cx + bar_w / 2, zero_y, fill=UP if bar >= 0 else DOWN, outline="")
            ly = bottom - (cum - lo) / span * (bottom - top)
            pts.extend([cx, ly])
            if i == 0 or i == n - 1 or (n <= 10):
                self.canvas.create_text(cx, bottom + 10, text=self.days[i][5:], fill=MUTED, font=("Microsoft YaHei UI", 8))
        if len(pts) >= 4:
            self.canvas.create_line(*pts, fill=PRIMARY, width=2, smooth=True)
        self.canvas.create_text(left - 6, top, text=format_signed_usd(hi), fill=MUTED, font=("Consolas", 8), anchor="e")
        self.canvas.create_text(left - 6, bottom, text=format_signed_usd(lo), fill=MUTED, font=("Consolas", 8), anchor="e")


class CategoryBarChart(ChartCard):
    def __init__(self, master, title: str, **kwargs):
        super().__init__(master, title, height=240, **kwargs)
        self.rows: list[NamedCount] = []

    def set_items(self, items: Iterable[NamedCount], limit: int = 8) -> None:
        self.rows = list(items)[:limit]
        self.redraw()

    def _has_data(self) -> bool:
        return any(item.count for item in self.rows)

    def _paint(self, w: int, h: int) -> None:
        left, right, top, bottom = 90, w - 48, 10, h - 12
        max_v = max((item.count for item in self.rows), default=1) or 1
        n = len(self.rows)
        gap = 8
        bar_h = max(12, min(22, (bottom - top - gap * n) / max(n, 1)))
        for i, item in enumerate(self.rows):
            y = top + i * (bar_h + gap)
            length = (right - left) * (item.count / max_v)
            self.canvas.create_rectangle(left, y, left + length, y + bar_h, fill=PRIMARY, outline="")
            self.canvas.create_text(left - 8, y + bar_h / 2, text=item.name[:12], fill=TEXT, font=("Microsoft YaHei UI", 9), anchor="e")
            self.canvas.create_text(left + length + 6, y + bar_h / 2, text=str(item.count), fill=MUTED, font=("Consolas", 9), anchor="w")


class HistogramChart(ChartCard):
    def __init__(self, master, title: str = "收益率分布", **kwargs):
        super().__init__(master, title, height=240, **kwargs)
        self.rows: list[NamedCount] = []

    def set_buckets(self, items: Sequence[NamedCount]) -> None:
        self.rows = list(items)
        self.redraw()

    def _has_data(self) -> bool:
        return any(item.count for item in self.rows)

    def _paint(self, w: int, h: int) -> None:
        left, right, top, bottom = 28, w - 12, 12, h - 36
        max_v = max((item.count for item in self.rows), default=1) or 1
        n = len(self.rows)
        slot = (right - left) / max(n, 1)
        bar_w = slot * 0.7
        self.canvas.create_line(left, bottom, right, bottom, fill=GRID)
        for i, item in enumerate(self.rows):
            cx = left + slot * i + slot / 2
            bh = 0 if max_v == 0 else (bottom - top) * (item.count / max_v)
            if item.name.startswith("-") or item.name.startswith("<"):
                color = DOWN
            elif item.name == "0%":
                color = FLAT
            else:
                color = UP
            self.canvas.create_rectangle(cx - bar_w / 2, bottom - bh, cx + bar_w / 2, bottom, fill=color, outline="")
            if item.count:
                self.canvas.create_text(cx, bottom - bh - 8, text=str(item.count), fill=TEXT, font=("Consolas", 8))
            self.canvas.create_text(cx, bottom + 12, text=item.name, fill=MUTED, font=("Microsoft YaHei UI", 8))
