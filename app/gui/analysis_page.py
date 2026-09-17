from __future__ import annotations

import queue
import threading
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from app.domain.enums import EventType, ReportPeriod, TaskStatus
from app.domain.models import AnalysisOptions, WalletAnalysisRequest, WalletReport
from app.gui.components.data_table import DataTable
from app.gui.components.progress_panel import ProgressPanel
from app.gui.components.stat_card import StatCard
from app.gui.theme import BG, DANGER, MUTED, PANEL, PRIMARY, SUCCESS, TEXT, WARN, font
from app.gui.worker import AnalysisWorker
from app.utils.time_utils import LOCAL_TZ, format_elapsed, period_window
from app.utils.validators import parse_wallet_lines, short_address, summarize_wallet_input, summarize_wallet_input


EXAMPLE_WALLET = "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV"

TOKEN_COLUMNS = [
    ("idx", "#", 40),
    ("symbol", "币种", 80),
    ("address", "代币合约", 120),
    ("platform", "来源平台", 100),
    ("acq", "获得方式", 90),
    ("mcap", "入场市值", 110),
    ("first_buy", "首笔买入", 110),
    ("amount", "首买数量", 100),
    ("buy_time", "买入时间", 140),
    ("created", "创建时间", 140),
    ("diff", "时差", 110),
    ("hold", "持仓时长", 100),
    ("buys", "买入笔数", 70),
    ("buy_usd", "买入总额", 110),
    ("sells", "卖出笔数", 70),
    ("sell_usd", "卖出总额", 110),
    ("realized", "已实现盈亏", 120),
    ("pnl", "总盈亏%", 90),
    ("missing", "缺失成本", 70),
    ("status", "状态", 80),
]
TRADE_COLUMNS = [
    ("time", "时间", 140),
    ("type", "类型", 90),
    ("symbol", "币种", 80),
    ("address", "代币合约", 120),
    ("amount", "数量", 90),
    ("usd", "USD金额", 110),
    ("sol", "SOL金额", 90),
    ("price", "价格USD", 100),
    ("gas_usd", "Gas USD", 90),
    ("gas_sol", "Gas SOL", 80),
    ("pnl", "单笔盈亏", 120),
    ("platform", "来源平台", 100),
    ("wallet", "钱包", 120),
    ("tx", "TxHash", 140),
]
WARN_COLUMNS = [
    ("wallet", "钱包", 120),
    ("token", "Token", 80),
    ("field", "字段", 90),
    ("value", "最终值", 140),
    ("status", "状态", 110),
    ("reason", "原因", 220),
    ("source", "数据来源", 140),
    ("est", "是否估算", 70),
]


class AnalysisPage(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self.app = app
        self.worker: Optional[AnalysisWorker] = None
        self.cancel_event = threading.Event()
        self.reports: list[WalletReport] = []
        self.current: Optional[WalletReport] = None
        self.period = ReportPeriod.D7
        self.job_id: Optional[str] = None
        self.page_key = "analysis"

        left = ctk.CTkFrame(self, width=320, fg_color=PANEL, corner_radius=0)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        right = ctk.CTkFrame(self, fg_color=BG)
        right.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(left, text="钱包地址", font=font(14, "bold"), text_color=TEXT, anchor="w").pack(fill="x", padx=16, pady=(16, 6))
        self.wallet_text = ctk.CTkTextbox(left, height=110, font=font(13))
        self.wallet_text.pack(fill="x", padx=16)
        self.wallet_text.bind("<KeyRelease>", lambda _e: self._refresh_wallet_stats())
        self.wallet_error = ctk.CTkLabel(left, text="", text_color=DANGER, font=font(11), anchor="w")
        self.wallet_error.pack(fill="x", padx=16)
        self.wallet_count = ctk.CTkLabel(left, text="有效钱包：0  重复：0  无效：0", font=font(11), text_color=MUTED, anchor="w")
        self.wallet_count.pack(fill="x", padx=16)
        self.mode_label = ctk.CTkLabel(left, text="模式：单钱包", font=font(11), text_color=MUTED, anchor="w")
        self.mode_label.pack(fill="x", padx=16)
        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=6)
        ctk.CTkButton(btns, text="从文件导入", width=90, height=28, command=self._import_file).pack(side="left")
        ctk.CTkButton(btns, text="粘贴示例", width=80, height=28, fg_color="#E5E7EB", text_color=TEXT, command=self._paste_example).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="清空", width=60, height=28, fg_color="#E5E7EB", text_color=TEXT, command=lambda: self.wallet_text.delete("1.0", "end")).pack(side="left")

        ctk.CTkLabel(left, text="时间范围", font=font(14, "bold"), text_color=TEXT, anchor="w").pack(fill="x", padx=16, pady=(10, 6))
        period_bar = ctk.CTkFrame(left, fg_color="transparent")
        period_bar.pack(fill="x", padx=16)
        self.period_buttons = {}
        for key, label in [(ReportPeriod.D7, "最近 7 天"), (ReportPeriod.D30, "最近 30 天"), (ReportPeriod.D90, "最近 90 天"), (ReportPeriod.ALL, "全部交易"), (ReportPeriod.CUSTOM, "自定义")]:
            btn = ctk.CTkButton(period_bar, text=label, height=28, width=88, command=lambda k=key: self._set_period(k))
            btn.pack(side="left", padx=2, pady=2)
            self.period_buttons[key] = btn
        date_row = ctk.CTkFrame(left, fg_color="transparent")
        date_row.pack(fill="x", padx=16, pady=6)
        self.start_var = ctk.StringVar()
        self.end_var = ctk.StringVar()
        ctk.CTkLabel(date_row, text="开始", font=font(12), text_color=MUTED).grid(row=0, column=0, sticky="w")
        ctk.CTkEntry(date_row, textvariable=self.start_var, width=130).grid(row=1, column=0, padx=(0, 8))
        ctk.CTkLabel(date_row, text="结束", font=font(12), text_color=MUTED).grid(row=0, column=1, sticky="w")
        ctk.CTkEntry(date_row, textvariable=self.end_var, width=130).grid(row=1, column=1)
        self._set_period(ReportPeriod.D7)

        ctk.CTkLabel(left, text="高级选项", font=font(14, "bold"), text_color=TEXT, anchor="w").pack(fill="x", padx=16, pady=(8, 4))
        opt = ctk.CTkFrame(left, fg_color="transparent")
        opt.pack(fill="x", padx=16)
        self.max_tx = ctk.CTkEntry(opt, width=80)
        self.max_tx.insert(0, "2500")
        ctk.CTkLabel(opt, text="每钱包交易上限", font=font(12), text_color=MUTED).grid(row=0, column=0, sticky="w")
        self.max_tx.grid(row=0, column=1, padx=8)
        self.opt_created = ctk.BooleanVar(value=True)
        self.opt_platform = ctk.BooleanVar(value=True)
        self.opt_transfer = ctk.BooleanVar(value=True)
        self.opt_fill = ctk.BooleanVar(value=True)
        self.opt_raw = ctk.BooleanVar(value=True)
        self.opt_pump = ctk.BooleanVar(value=False)
        for var, label in [
            (self.opt_created, "获取 Token 创建时间"),
            (self.opt_platform, "获取来源平台/池子"),
            (self.opt_transfer, "识别 Transfer / Bridge"),
            (self.opt_fill, "自动补齐缺失字段"),
            (self.opt_raw, "保存原始 API JSON"),
            (self.opt_pump, "仅分析 Pump.fun Token"),
        ]:
            ctk.CTkCheckBox(left, text=label, variable=var, font=font(12)).pack(anchor="w", padx=16, pady=2)

        start_bar = ctk.CTkFrame(left, fg_color="transparent")
        start_bar.pack(fill="x", padx=16, pady=12)
        self.start_btn = ctk.CTkButton(start_bar, text="开始分析", height=36, command=self.start_analysis)
        self.start_btn.pack(side="left", expand=True, fill="x")
        self.stop_btn = ctk.CTkButton(start_bar, text="停止", height=36, fg_color=DANGER, width=80, command=self.stop_analysis, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.progress = ProgressPanel(left)
        self.progress.pack(fill="x", padx=12, pady=(0, 12))

        header = ctk.CTkFrame(right, fg_color=PANEL)
        header.pack(fill="x", padx=12, pady=12)
        self.title_label = ctk.CTkLabel(header, text="分析任务", font=font(20, "bold"), text_color=TEXT, anchor="w")
        self.title_label.pack(fill="x", padx=16, pady=(12, 0))
        self.meta_label = ctk.CTkLabel(header, text="Job：-    状态：等待分析    耗时：-", font=font(13), text_color=MUTED, anchor="w")
        self.meta_label.pack(fill="x", padx=16, pady=(4, 0))
        self.job_summary = ctk.CTkLabel(header, text="钱包 0/0 · Token 0/0 · Keys - · 429 0 · 缓存 -", font=font(12), text_color=MUTED, anchor="w")
        self.job_summary.pack(fill="x", padx=16, pady=(2, 4))
        self.key_status = ctk.CTkLabel(header, text="API Keys：未加载", font=font(12), text_color=MUTED, anchor="w", justify="left")
        self.key_status.pack(fill="x", padx=16, pady=(0, 8))
        self.rate_banner = ctk.CTkLabel(header, text="", font=font(12), text_color=WARN, anchor="w")
        self.rate_banner.pack(fill="x", padx=16, pady=(0, 8))

        cards = ctk.CTkFrame(right, fg_color="transparent")
        cards.pack(fill="x", padx=12)
        self.cards = {}
        for key, title in [
            ("tokens", "代币总数"),
            ("buysell", "买入 / 卖出"),
            ("realized", "GMGN 已实现盈亏"),
            ("total", "GMGN 总盈亏"),
            ("open", "当前持仓数"),
            ("gas", "Gas 总费用"),
            ("special", "特殊获得资产数"),
            ("missing", "缺失成本数"),
        ]:
            card = StatCard(cards, title)
            card.pack(side="left", expand=True, fill="x", padx=4)
            self.cards[key] = card

        self.wallet_table = DataTable(
            right,
            [
                ("wallet", "钱包", 110),
                ("state", "状态", 90),
                ("tokens", "Token", 60),
                ("done", "已完成", 60),
                ("stage", "当前阶段", 90),
                ("key", "使用Key", 80),
                ("reqs", "API请求", 70),
                ("rl", "429", 50),
                ("cache", "缓存", 60),
                ("elapsed", "耗时", 70),
            ],
        )
        self.wallet_table.pack(fill="x", padx=12)
        self.wallet_table.tree.bind("<Double-1>", lambda _e: self._select_wallet_row())

        tabs = ctk.CTkTabview(right)
        tabs.pack(fill="both", expand=True, padx=12, pady=12)
        self.token_tab = tabs.add("代币分析")
        self.trade_tab = tabs.add("交易明细")
        self.pos_tab = tabs.add("持仓分析")
        self.pnl_tab = tabs.add("盈亏统计")
        self.plat_tab = tabs.add("平台分布")
        self.warn_tab = tabs.add("异常与补全")
        self.log_tab = tabs.add("运行日志")
        self.raw_tab = tabs.add("原始数据")

        self.token_table = DataTable(self.token_tab, TOKEN_COLUMNS)
        self.token_table.pack(fill="both", expand=True)
        self.token_table.set_filters(["全部", "有盈利", "亏损", "缺失成本", "特殊获得", "非 Launchpad", "仍持仓", "已清仓"])
        self.trade_table = DataTable(self.trade_tab, TRADE_COLUMNS)
        self.trade_table.pack(fill="both", expand=True)
        self.trade_table.set_filters(["全部", "buy", "sell", "transferIn", "transferOut"])
        self.pos_table = DataTable(self.pos_tab, TOKEN_COLUMNS)
        self.pos_table.pack(fill="both", expand=True)
        self.pnl_table = DataTable(
            self.pnl_tab,
            [("symbol", "币种", 90), ("address", "代币合约", 140), ("fifo", "本地FIFO已实现", 140), ("gmgn", "GMGN说明", 280), ("missing", "缺失成本", 80), ("status", "状态", 90)],
        )
        self.pnl_table.pack(fill="both", expand=True)
        self.plat_table = DataTable(self.plat_tab, [("platform", "来源平台", 160), ("count", "Token数", 80), ("buys", "买入笔数", 90), ("sells", "卖出笔数", 90)])
        self.plat_table.pack(fill="both", expand=True)
        self.warn_table = DataTable(self.warn_tab, WARN_COLUMNS)
        self.warn_table.pack(fill="both", expand=True)
        self.run_log = ctk.CTkTextbox(self.log_tab, font=font(12))
        self.run_log.pack(fill="both", expand=True, padx=8, pady=8)
        self.raw_box = ctk.CTkTextbox(self.raw_tab, font=font(12))
        self.raw_box.pack(fill="both", expand=True, padx=8, pady=8)
        self._wallet_rows: dict[str, dict] = {}
        self._refresh_keys()

    def _refresh_wallet_stats(self) -> None:
        stats = summarize_wallet_input(self.wallet_text.get("1.0", "end"))
        self.wallet_count.configure(text=f"有效钱包：{stats['valid']}  重复：{stats['duplicate']}  无效：{stats['invalid']}")
        self.mode_label.configure(text="模式：批量任务" if stats["valid"] > 1 else "模式：单钱包")

    def _refresh_keys(self) -> None:
        try:
            items = self.app.credentials.snapshot()
        except Exception:
            items = []
        if not items:
            self.key_status.configure(text="API Keys：未配置")
            return
        healthy = sum(1 for i in items if i["state"] == "HEALTHY")
        cooldown = sum(1 for i in items if i["state"] in ("RATE_LIMITED", "COOLDOWN"))
        lines = [f"API Keys：{healthy} Healthy / {cooldown} Cooldown"]
        for item in items:
            extra = f"利用率：{int((item.get('utilization') or 0)*100)}% inflight：{item.get('inflight') or 0}"
            if item["state"] in ("RATE_LIMITED", "COOLDOWN") and item.get("cooldown_until"):
                extra = f"恢复：{int(item['cooldown_until'])}"
            lines.append(f"{item['masked']}  状态：{item['state']}  {extra}")
        self.key_status.configure(text="\n".join(lines))

    def _append_run_log(self, text: str) -> None:
        try:
            self.run_log.insert("end", text + "\n")
            self.run_log.see("end")
        except Exception:
            pass

    def _select_wallet_row(self) -> None:
        sel = self.wallet_table.tree.selection()
        if not sel:
            return
        values = self.wallet_table.tree.item(sel[0], "values")
        if not values:
            return
        short = values[0]
        for report in self.reports:
            if short_address(report.request.wallet_address) == short or report.request.wallet_address.startswith(str(short).split("...")[0]):
                self.render_report(report)
                return

    def _set_period(self, period: ReportPeriod) -> None:
        self.period = period
        for key, btn in self.period_buttons.items():
            btn.configure(fg_color=PRIMARY if key == period else "#E5E7EB", text_color="#FFFFFF" if key == period else TEXT)
        now = datetime.now(tz=LOCAL_TZ)
        if period == ReportPeriod.D7:
            start = now - timedelta(days=7)
        elif period == ReportPeriod.D30:
            start = now - timedelta(days=30)
        elif period == ReportPeriod.D90:
            start = now - timedelta(days=90)
        elif period == ReportPeriod.ALL:
            start = datetime(2020, 1, 1, tzinfo=LOCAL_TZ)
        else:
            start = now - timedelta(days=7)
        self.start_var.set(start.strftime("%Y-%m-%d"))
        self.end_var.set(now.strftime("%Y-%m-%d"))

    def _import_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not path:
            return
        text = open(path, encoding="utf-8").read()
        self.wallet_text.delete("1.0", "end")
        self.wallet_text.insert("1.0", text)

    def _paste_example(self) -> None:
        self.wallet_text.delete("1.0", "end")
        self.wallet_text.insert("1.0", EXAMPLE_WALLET)

    def start_analysis(self) -> None:
        self._refresh_wallet_stats()
        wallets, errors = parse_wallet_lines(self.wallet_text.get("1.0", "end"))
        stats = summarize_wallet_input(self.wallet_text.get("1.0", "end"))
        if errors:
            self.wallet_error.configure(text="；".join(f"{e.address}: {e.reason}" for e in errors[:3]))
        else:
            self.wallet_error.configure(text="")
        if not wallets:
            messagebox.showerror("无法开始", "请输入有效 Solana 钱包地址")
            return
        if not self.app.config.has_api_key:
            messagebox.showerror("缺少 API Key", "请先在系统设置中填写 GMGN_API_KEY")
            self.app.show_page("settings")
            return
        try:
            start = datetime.strptime(self.start_var.get().strip(), "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
            end = datetime.strptime(self.end_var.get().strip() + " 23:59:59", "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
        except ValueError:
            messagebox.showerror("日期错误", "开始/结束日期格式应为 YYYY-MM-DD")
            return
        start_ts, end_ts = period_window(self.period, start, end)
        options = AnalysisOptions(
            fetch_token_created_at=self.opt_created.get(),
            fetch_platform_pool=self.opt_platform.get(),
            detect_transfer_bridge=self.opt_transfer.get(),
            autofill_missing=self.opt_fill.get(),
            save_raw_json=self.opt_raw.get(),
            pumpfun_only=self.opt_pump.get(),
        )
        max_tx = int(self.max_tx.get() or 2500)
        requests = [
            WalletAnalysisRequest(
                wallet_address=w,
                chain="sol",
                period=self.period,
                start_time=start_ts,
                end_time=end_ts,
                max_transactions=max_tx,
                options=options,
            )
            for w in wallets
        ]
        self.cancel_event = threading.Event()
        page_key = getattr(self, "page_key", "analysis")
        self.worker = AnalysisWorker(
            requests,
            self.app.config,
            self.app.ui_queue,
            self.cancel_event,
            self.app.db,
            self.app.limiter,
            page=page_key,
            credentials=self.app.credentials,
        )
        self.job_id = self.worker.job_id
        self.reports = []
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        mode = "单钱包" if len(wallets) == 1 else f"批量任务 · {len(wallets)} 个钱包"
        self.title_label.configure(text=f"分析任务（{mode}）")
        self.meta_label.configure(text=f"Job：{self.job_id[:8]}    状态：RUNNING    钱包：0/{len(wallets)}")
        self.job_summary.configure(text=f"钱包 0/{len(wallets)} · Token 0/0 · 429 0 · 缓存 -")
        self.wallet_table.set_rows(
            [
                {
                    "wallet": short_address(w),
                    "state": "QUEUED",
                    "tokens": 0,
                    "done": 0,
                    "stage": "WAITING",
                    "key": "-",
                    "reqs": 0,
                    "rl": 0,
                    "cache": "-",
                    "elapsed": "-",
                    "_copy": w,
                }
                for w in wallets
            ]
        )
        self._refresh_keys()
        self.progress.update_progress("开始分析", 0, 0, wallets[0], "")
        self._append_run_log(f"JOB_STARTED {self.job_id} {mode}")
        self.app.log_panel.append(f"开始分析 Job {self.job_id[:8]} {mode} {', '.join(short_address(w) for w in wallets)}")
        self.worker.start()

    def stop_analysis(self) -> None:
        self.cancel_event.set()
        self.app.log_panel.append("已请求停止，等待当前请求安全退出", "WARNING")

    def handle_message(self, msg: dict) -> None:
        jid = msg.get("job_id")
        if jid and self.job_id and jid != self.job_id:
            return
        kind = msg.get("type")
        self._refresh_keys()
        if kind in ("progress", "WALLET_STARTED", "WALLET_WAITING_API", "RATE_LIMITED", "KEY_RECOVERED", "wallet_done"):
            self._append_run_log(f"{kind} {msg.get('wallet') or ''} {msg.get('message') or ''}".strip())
        if kind == "progress":
            self.progress.update_progress(
                msg.get("message", ""),
                int(msg.get("done") or 0),
                int(msg.get("total") or 0),
                short_address(msg.get("wallet") or ""),
                short_address(msg.get("token") or ""),
            )
        elif kind == "api_state":
            self.progress.api_label.configure(text=str(msg.get("state") or "API 正常"))
            self.app.set_api_status(str(msg.get("state") or "API 正常"))
        elif kind in ("WALLET_WAITING_API", "RATE_LIMITED"):
            text = msg.get("message") or "API 限流，等待恢复"
            self.rate_banner.configure(text=text, text_color=WARN)
            self.progress.api_label.configure(text=text)
            self.app.set_api_status(text)
            self.app.log_panel.append(text, "WARNING")
        elif kind == "KEY_RECOVERED":
            self.rate_banner.configure(text="Key 已恢复，任务继续")
            self.app.log_panel.append("Key 已恢复", "SUCCESS")
        elif kind == "wallet_done":
            report: WalletReport = msg["report"]
            self.reports.append(report)
            self.render_report(report)
            self.app.log_panel.append(f"SUCCESS {short_address(report.request.wallet_address)} 完成，Excel={report.excel_path}", "SUCCESS")
        elif kind in ("done", "cancelled", "error"):
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            reports = msg.get("reports") or self.reports
            if reports:
                self.render_report(reports[-1])
            if kind == "cancelled":
                self.meta_label.configure(text=self.meta_label.cget("text").replace("分析完成", "已取消") if "分析完成" in self.meta_label.cget("text") else "状态：已取消")
                self.app.log_panel.append("分析已取消", "WARNING")
            elif kind == "error":
                self.app.log_panel.append(msg.get("message") or "分析失败", "ERROR")
                messagebox.showerror("分析失败", msg.get("message") or "未知错误")
            else:
                self.rate_banner.configure(text="")
                self.app.log_panel.append("全部任务完成", "SUCCESS")

    def render_report(self, report: WalletReport) -> None:
        self.current = report
        self.meta_label.configure(
            text=f"钱包：{short_address(report.request.wallet_address)}    状态：{report.status.value}    耗时：{format_elapsed(report.elapsed_seconds)}"
        )
        s = report.summary
        self.cards["tokens"].set_value(str(s.token_count))
        self.cards["buysell"].set_value(f"{s.buy_count} / {s.sell_count}")
        self.cards["realized"].set_value(str(s.gmgn_realized_profit.export("usd_compact")))
        self.cards["total"].set_value(str(s.gmgn_total_profit.export("usd_compact")))
        self.cards["open"].set_value(str(s.open_positions))
        self.cards["gas"].set_value(str(s.gas_total_usd.export("usd_compact")))
        self.cards["special"].set_value(str(s.special_acquisition_count))
        self.cards["missing"].set_value(str(s.missing_cost_count))
        from app.services.completeness_service import CompletenessService

        complete = CompletenessService()
        token_rows = []
        for idx, token in enumerate(report.tokens, start=1):
            row = complete.token_export_row(token)
            filters = ["全部"]
            if token.missing_cost_count:
                filters.append("缺失成本")
            if token.acquisition.acquisition_type.value != "BUY":
                filters.append("特殊获得")
            if str(token.source_platform.export("text")) in {"非 Launchpad", "未知来源"}:
                filters.append("非 Launchpad")
            if token.position_status.value == "仍持仓":
                filters.append("仍持仓")
            else:
                filters.append("已清仓")
            fifo_text = str(token.fifo_realized_profit.export("text"))
            if fifo_text.startswith("-"):
                filters.append("亏损")
                tag = "loss"
            elif any(ch.isdigit() for ch in fifo_text) and fifo_text not in {"0", "0.0"}:
                filters.append("有盈利")
                tag = "profit"
            else:
                tag = "special" if token.acquisition.acquisition_type.value != "BUY" else ""
            token_rows.append(
                {
                    "idx": idx,
                    "symbol": row["币种"],
                    "address": short_address(token.token_address),
                    "platform": row["来源平台"],
                    "acq": row["获得方式"],
                    "mcap": row["入场市值"],
                    "first_buy": row["首笔买入"],
                    "amount": row["首买数量"],
                    "buy_time": row["买入时间"],
                    "created": row["创建时间"],
                    "diff": row["时差"],
                    "hold": row["持仓时长"],
                    "buys": row["买入笔数"],
                    "buy_usd": row["买入总额"],
                    "sells": row["卖出笔数"],
                    "sell_usd": row["卖出总额"],
                    "realized": row["本地FIFO已实现"],
                    "pnl": row["总盈亏%"],
                    "missing": row["缺失成本"],
                    "status": row["状态"],
                    "_copy": token.token_address,
                    "_filters": " ".join(filters),
                    "_filter": filters[1] if len(filters) > 1 else "全部",
                    "_tag": tag,
                }
            )
        self.token_table.set_rows(token_rows)
        self.pos_table.set_rows([r for r in token_rows if "仍持仓" in r.get("_filters", "")])
        platforms = {t.token_address: str(t.source_platform.export("text")) for t in report.tokens}
        trade_rows = []
        for tr in report.trades:
            row = complete.trade_export_row(tr, platforms.get(tr.token_address, "未知来源"))
            trade_rows.append(
                {
                    "time": row["时间"],
                    "type": row["类型"],
                    "symbol": row["币种"],
                    "address": short_address(tr.token_address),
                    "amount": row["数量"],
                    "usd": row["USD金额"],
                    "sol": row["SOL金额"],
                    "price": row["价格USD"],
                    "gas_usd": row["Gas USD"],
                    "gas_sol": row["Gas SOL"],
                    "pnl": row["单笔盈亏"],
                    "platform": row["来源平台"],
                    "wallet": short_address(tr.wallet_address),
                    "tx": short_address(tr.tx_hash, 6, 4),
                    "_copy": tr.tx_hash,
                    "_filter": tr.event_type.value,
                    "_tag": "profit" if tr.event_type == EventType.BUY else ("loss" if tr.event_type == EventType.SELL else "special"),
                }
            )
        self.trade_table.set_rows(trade_rows)
        self.pnl_table.set_rows(
            [
                {
                    "symbol": t.symbol,
                    "address": short_address(t.token_address),
                    "fifo": t.fifo_realized_profit.export("usd"),
                    "gmgn": t.realized_profit.export("text"),
                    "missing": t.missing_cost_count,
                    "status": t.status.value,
                    "_copy": t.token_address,
                }
                for t in report.tokens
            ]
        )
        plat_count: dict[str, dict[str, int]] = {}
        for token in report.tokens:
            name = str(token.source_platform.export("text"))
            bucket = plat_count.setdefault(name, {"count": 0, "buys": 0, "sells": 0})
            bucket["count"] += 1
            bucket["buys"] += token.buy_count
            bucket["sells"] += token.sell_count
        self.plat_table.set_rows([{"platform": k, "count": v["count"], "buys": v["buys"], "sells": v["sells"]} for k, v in plat_count.items()])
        self.warn_table.set_rows(
            [
                {
                    "wallet": short_address(w.wallet_address),
                    "token": w.token_symbol,
                    "field": w.field_name,
                    "value": w.final_value,
                    "status": w.status,
                    "reason": w.reason,
                    "source": w.source,
                    "est": "是" if w.estimated else "否",
                    "_copy": w.token_address,
                }
                for w in report.warnings
            ]
        )
        self.raw_box.delete("1.0", "end")
        raw_text = "\n".join(report.raw_paths) if report.raw_paths else "未保存原始 JSON"
        self.raw_box.insert("1.0", f"Excel: {report.excel_path}\nJSON: {report.json_path}\n请求数: {report.api_stats.requests}\n缓存命中率: {report.api_stats.cache_hit_rate}\n\n原始文件:\n{raw_text}")
        self.app.set_cache_rate(report.api_stats.cache_hit_rate)
        self.app.refresh_history()
