from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import customtkinter as ctk

from app.gui.components.charts import CategoryBarChart, ComboChart, DonutChart, HistogramChart, SignedBarChart
from app.gui.theme import BG, BORDER, DANGER, MUTED, PANEL, SUCCESS, TEXT, font
from app.gui.viz_metrics import (
    VizSnapshot,
    format_pct,
    format_signed_usd,
    snapshot_from_payload,
    snapshot_from_report,
    snapshot_from_summary_row,
)
from app.utils.validators import short_address


class VizKpi(ctk.CTkFrame):
    def __init__(self, master, title: str, **kwargs):
        super().__init__(master, fg_color=PANEL, corner_radius=10, border_width=1, border_color=BORDER, **kwargs)
        self.title_label = ctk.CTkLabel(self, text=title, text_color=MUTED, font=font(12), anchor="w")
        self.title_label.pack(fill="x", padx=12, pady=(10, 0))
        self.value_label = ctk.CTkLabel(self, text="—", text_color=TEXT, font=font(18, "bold"), anchor="w")
        self.value_label.pack(fill="x", padx=12, pady=(4, 12))

    def set_value(self, value: str, color: str = TEXT) -> None:
        self.value_label.configure(text=value or "—", text_color=color)


class VizPage(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self.app = app
        self._dirty = True
        self._report_options: list[tuple[str, str]] = []
        self._current_key = ""
        self._state = "empty"

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(head, text="数据可视化", font=font(20, "bold"), text_color=TEXT, anchor="w").pack(side="left")
        ctk.CTkButton(head, text="刷新", width=72, height=30, fg_color="#E5E7EB", text_color=TEXT, command=self.refresh).pack(side="right")
        self.picker = ctk.CTkComboBox(head, width=360, height=30, command=self._on_pick, values=["暂无报告"])
        self.picker.pack(side="right", padx=8)
        self.picker.set("暂无报告")

        self.meta = ctk.CTkLabel(self, text="选择一份历史报告，查看盈亏结构、胜率和每日曲线。", font=font(13), text_color=MUTED, anchor="w")
        self.meta.pack(fill="x", padx=20, pady=(0, 4))

        self.body = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0)
        self.body.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.empty_card = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=10, border_width=1, border_color=BORDER)
        self.empty_label = ctk.CTkLabel(
            self.empty_card,
            text="还没有可画的报告。先到「分析任务」跑一次钱包，完成后回到这里。",
            font=font(14),
            text_color=MUTED,
            justify="left",
            anchor="w",
        )
        self.empty_label.pack(fill="x", padx=20, pady=28)

        self.dash = ctk.CTkFrame(self.body, fg_color="transparent")
        self.insight = ctk.CTkLabel(self.dash, text="", font=font(14, "bold"), text_color=TEXT, anchor="w", wraplength=1100, justify="left")
        self.insight.pack(fill="x", padx=8, pady=(4, 8))

        kpi_row = ctk.CTkFrame(self.dash, fg_color="transparent")
        kpi_row.pack(fill="x", padx=4, pady=(0, 8))
        self.kpis: dict[str, VizKpi] = {}
        for key, title in [
            ("realized", "已实现盈亏"),
            ("total", "总盈亏"),
            ("win_rate", "胜率"),
            ("pf", "盈亏比"),
            ("tokens", "代币 / 持仓"),
            ("flow", "买入 / 卖出"),
            ("gas", "Gas"),
        ]:
            card = VizKpi(kpi_row, title)
            card.pack(side="left", expand=True, fill="x", padx=4)
            self.kpis[key] = card

        grid = ctk.CTkFrame(self.dash, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=4, pady=4)
        grid.grid_columnconfigure(0, weight=3)
        grid.grid_columnconfigure(1, weight=2)
        self.contrib = SignedBarChart(grid, "代币盈亏贡献 Top 10")
        self.contrib.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.donut = DonutChart(grid, "胜负结构")
        self.donut.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        self.daily = ComboChart(grid, "每日已实现盈亏 / 累计曲线")
        self.daily.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.platforms = CategoryBarChart(grid, "来源平台")
        self.platforms.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)
        self.hist = HistogramChart(grid, "收益率分布")
        self.hist.grid(row=2, column=0, sticky="nsew", padx=4, pady=4)
        self.acq = CategoryBarChart(grid, "获得方式")
        self.acq.grid(row=2, column=1, sticky="nsew", padx=4, pady=4)

        self._show_state("empty")

    def mark_dirty(self) -> None:
        self._dirty = True

    def refresh_if_dirty(self) -> None:
        if self._dirty:
            self.refresh()

    def _show_state(self, state: str) -> None:
        self._state = state
        if state == "ready":
            self.empty_card.pack_forget()
            self.dash.pack(fill="both", expand=True)
            return
        self.dash.pack_forget()
        if not self.empty_card.winfo_manager():
            self.empty_card.pack(fill="x", padx=8, pady=12)

    def refresh(self) -> None:
        previous = self._current_key
        self._report_options = self._collect_options()
        labels = [label for _, label in self._report_options]
        if not labels:
            self.picker.configure(values=["暂无报告"])
            self.picker.set("暂无报告")
            self._current_key = ""
            self.meta.configure(text="选择一份历史报告，查看盈亏结构、胜率和每日曲线。")
            self.empty_label.configure(text="还没有可画的报告。先到「分析任务」跑一次钱包，完成后回到这里。")
            self._show_state("empty")
            self._dirty = False
            return
        self.picker.configure(values=labels)
        key = previous if any(k == previous for k, _ in self._report_options) else self._report_options[0][0]
        label = next(lbl for k, lbl in self._report_options if k == key)
        self.picker.set(label)
        self._load_key(key)

    def _on_pick(self, _value: str) -> None:
        label = self.picker.get()
        for key, text in self._report_options:
            if text == label:
                self._load_key(key)
                return

    def _collect_options(self) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = []
        analysis = self.app.pages.get("analysis")
        current = getattr(analysis, "current", None) if analysis is not None else None
        if current is not None:
            wallet = getattr(getattr(current, "request", None), "wallet_address", "") or ""
            options.append(("live", f"当前分析 · {short_address(wallet)}"))
        reports = self.app.db_repos.list_reports(40)
        for row in reports:
            created = datetime.fromtimestamp(row["created_at"]).strftime("%m-%d %H:%M") if row.get("created_at") else ""
            label = f"{created}  {short_address(row.get('wallet_address') or '')}  {row.get('period') or ''}  {row.get('status') or ''}"
            options.append((f"report:{row['id']}", label.strip()))
        return options

    def _load_key(self, key: str) -> None:
        self._current_key = key
        try:
            snap = self._snapshot_for(key)
        except Exception as exc:
            self.empty_label.configure(text=f"这份报告读不出来：{exc}")
            self._show_state("error")
            self._dirty = False
            return
        if snap is None:
            self.empty_label.configure(text="还没有可画的报告。先到「分析任务」跑一次钱包，完成后回到这里。")
            self._show_state("empty")
            self._dirty = False
            return
        self._render(snap)
        self._dirty = False

    def _snapshot_for(self, key: str) -> VizSnapshot | None:
        if key == "live":
            analysis = self.app.pages.get("analysis")
            current = getattr(analysis, "current", None) if analysis is not None else None
            if current is None:
                return None
            return snapshot_from_report(current)
        if key.startswith("report:"):
            report_id = key.split(":", 1)[1]
            rows = [row for row in self.app.db_repos.list_reports(80) if str(row.get("id")) == report_id]
            if not rows:
                return None
            row = rows[0]
            path = str(row.get("json_path") or "")
            if path and Path(path).exists():
                with open(path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                return snapshot_from_payload(payload, source=path)
            return snapshot_from_summary_row(row)
        return None

    def _render(self, snap: VizSnapshot) -> None:
        self._show_state("ready")
        src = "当前内存报告" if snap.source == "当前分析" else "本地 JSON"
        self.meta.configure(text=f"{snap.wallet_short}  ·  {snap.period}  ·  {snap.status}  ·  {src}")
        self.insight.configure(text=snap.insight)
        self.kpis["realized"].set_value(format_signed_usd(snap.realized), _pnl_color(snap.realized))
        self.kpis["total"].set_value(format_signed_usd(snap.total), _pnl_color(snap.total))
        self.kpis["win_rate"].set_value(format_pct(snap.win_rate), TEXT)
        if snap.profit_factor == float("inf"):
            pf = "∞"
        elif snap.profit_factor is None:
            pf = "—"
        else:
            pf = f"{snap.profit_factor:.2f}"
        self.kpis["pf"].set_value(pf, TEXT)
        self.kpis["tokens"].set_value(f"{snap.token_count} / {snap.open_positions}", TEXT)
        self.kpis["flow"].set_value(f"{snap.buy_count} / {snap.sell_count}", TEXT)
        self.kpis["gas"].set_value(format_signed_usd(snap.gas) if snap.gas is not None else "—", TEXT)
        self.contrib.set_tokens(snap.tokens)
        self.donut.set_outcome(snap.win_count, snap.loss_count, snap.flat_count, snap.win_rate)
        if snap.daily:
            self.daily.set_daily([p.day for p in snap.daily], [p.realized for p in snap.daily], [p.cumulative for p in snap.daily])
        else:
            self.daily.set_daily([], [], [])
            self.daily.set_empty("没有带日期的成交，无法画每日曲线")
        self.platforms.set_items(snap.platforms)
        self.hist.set_buckets(snap.pnl_buckets)
        self.acq.set_items(snap.acquisitions)
        if not snap.has_detail:
            self.contrib.set_empty("只有汇总数字，明细 JSON 不在了。重新分析后图表会完整。")
            self.donut.set_empty("缺少代币明细")
            self.platforms.set_empty("缺少代币明细")
            self.hist.set_empty("缺少收益率")
            self.acq.set_empty("缺少获得方式")


def _pnl_color(value: float | None) -> str:
    if value is None:
        return TEXT
    if value > 0:
        return SUCCESS
    if value < 0:
        return DANGER
    return TEXT
