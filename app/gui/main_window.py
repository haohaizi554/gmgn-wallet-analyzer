from __future__ import annotations

import queue
import sys
from tkinter import ttk

import customtkinter as ctk

from app.api.credential_pool import CredentialPool
from app.api.rate_limiter import WeightedRateLimiter
from app.config import AppConfig, load_config
from app.gui.about_page import AboutPage
from app.gui.analysis_page import AnalysisPage
from app.gui.components.log_panel import LogPanel
from app.gui.export_page import ExportPage
from app.gui.history_page import HistoryPage
from app.gui.settings_page import SettingsPage
from app.gui.sidebar import Sidebar
from app.gui.theme import BG, MUTED, PANEL, TEXT, apply_theme, font
from app.storage.database import Database
from app.storage.repositories import Repositories
from app.utils.logger import attach_queue_handler, get_logger, setup_logging
from app.utils.paths import ensure_runtime_dirs
from app.version import APP_NAME, __version__

logger = get_logger("gmgn.gui")


class MainWindow(ctk.CTk):
    def __init__(self) -> None:
        apply_theme()
        super().__init__()
        ensure_runtime_dirs()
        setup_logging()
        self.title(f"{APP_NAME} v{__version__}")
        self.geometry("1500x920")
        self.minsize(1200, 760)
        self.configure(fg_color=BG)
        self.config: AppConfig = load_config()
        self.db = Database()
        self.db_repos = Repositories(self.db)
        keys = self.config.api_keys or ([self.config.api_key] if self.config.api_key else [])
        self.credentials = CredentialPool(
            keys,
            rate=self.config.rate,
            capacity=self.config.capacity,
            target_utilization=self.config.target_utilization,
            initial_utilization=getattr(self.config, "initial_utilization", 0.60),
            safety_margin=getattr(self.config, "reset_safety_margin", 3.0),
        )
        self.limiter = self.credentials.all()[0].limiter if self.credentials.all() else WeightedRateLimiter(
            self.config.rate,
            self.config.capacity,
            target_utilization=self.config.target_utilization,
            initial_utilization=getattr(self.config, "initial_utilization", 0.60),
            safety_margin=getattr(self.config, "reset_safety_margin", 3.0),
        )
        self.ui_queue: queue.Queue = queue.Queue()
        self.pages: dict[str, ctk.CTkFrame] = {}

        root = ctk.CTkFrame(self, fg_color=BG)
        root.pack(fill="both", expand=True)
        self.sidebar = Sidebar(root, self.show_page)
        self.sidebar.pack(side="left", fill="y")
        body = ctk.CTkFrame(root, fg_color=BG)
        body.pack(side="left", fill="both", expand=True)
        self.page_host = ctk.CTkFrame(body, fg_color=BG)
        self.page_host.pack(fill="both", expand=True)
        self.log_panel = LogPanel(body)
        self.log_panel.pack(fill="x")
        attach_queue_handler(self._enqueue_log, "gmgn")
        self.status = ctk.CTkFrame(self, height=32, fg_color=PANEL)
        self.status.pack(fill="x")
        self.api_status = ctk.CTkLabel(self.status, text="API 未测试", font=font(12), text_color=MUTED)
        self.api_status.pack(side="left", padx=12)
        self.plan_label = ctk.CTkLabel(self.status, text=f"套餐：{self.config.plan}", font=font(12), text_color=MUTED)
        self.plan_label.pack(side="left", padx=12)
        self.limit_label = ctk.CTkLabel(self.status, text=f"限额：{int(self.config.rate)}u/s 目标：{int(self.config.target_utilization*100)}%", font=font(12), text_color=MUTED)
        self.limit_label.pack(side="left", padx=12)
        self.db_label = ctk.CTkLabel(self.status, text="数据库：正常", font=font(12), text_color=MUTED)
        self.db_label.pack(side="left", padx=12)
        self.cache_label = ctk.CTkLabel(self.status, text="缓存命中：0%", font=font(12), text_color=MUTED)
        self.cache_label.pack(side="left", padx=12)
        ctk.CTkLabel(self.status, text=f"版本：v{__version__}", font=font(12), text_color=MUTED).pack(side="right", padx=12)

        self.pages["analysis"] = AnalysisPage(self.page_host, self)
        self.pages["history"] = HistoryPage(self.page_host, self)
        self.pages["export"] = ExportPage(self.page_host, self)
        self.pages["settings"] = SettingsPage(self.page_host, self)
        self.pages["about"] = AboutPage(self.page_host)
        self.show_page("analysis")
        self.sidebar.highlight("analysis")
        self.after(80, self._poll_queue)
        if getattr(self.config, "enable_moralis", False) and getattr(self.config, "moralis_api_keys", None):
            self.log_panel.append(f"Moralis 主索引已启用，{len(self.config.moralis_api_keys)} 把 Key 轮换。")
        elif getattr(self.config, "enable_moralis", False):
            self.log_panel.append("ENABLE_MORALIS=true 但未配置 MORALIS_API_KEY，将走 Solana RPC。", "WARNING")
        if not getattr(self.config, "helius_api_key", ""):
            self.log_panel.append("Helius: NOT CONFIGURED (Optional)")
        if not self.config.has_api_key:
            self.log_panel.append("GMGN 未配置，仅作可选辅助。")
        self.log_panel.append("配置已加载，可以开始分析。")

    def show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        for item in self.pages.values():
            item.pack_forget()
        page.pack(fill="both", expand=True)
        if key == "history":
            self.refresh_history()

    def reload_config(self) -> None:
        self.config = load_config()
        new_keys = self.config.api_keys or ([self.config.api_key] if self.config.api_key else [])
        current = [c.api_key for c in self.credentials.all()]
        if current != new_keys:
            self.credentials = CredentialPool(
                new_keys,
                rate=self.config.rate,
                capacity=self.config.capacity,
                target_utilization=self.config.target_utilization,
                initial_utilization=getattr(self.config, "initial_utilization", 0.60),
                safety_margin=getattr(self.config, "reset_safety_margin", 3.0),
            )
            if self.credentials.all():
                self.limiter = self.credentials.all()[0].limiter
        else:
            for cred in self.credentials.all():
                cred.limiter.server_rate = self.config.rate
                cred.limiter.capacity = self.config.capacity
                cred.limiter.target_utilization = self.config.target_utilization
                cred.limiter.safety_margin = getattr(self.config, "reset_safety_margin", 3.0)
                if cred.limiter._adaptive_target > cred.limiter.target_utilization:
                    cred.limiter._adaptive_target = cred.limiter.target_utilization
                    cred.limiter.rate = cred.limiter.server_rate * cred.limiter._adaptive_target
        self.plan_label.configure(text=f"套餐：{self.config.plan}")
        self.limit_label.configure(text=f"限额：{int(self.config.rate)}u/s 目标：{int(self.config.target_utilization*100)}%")

    def set_api_status(self, text: str) -> None:
        self.api_status.configure(text=text)
        self.limit_label.configure(text=self.limiter.snapshot().display)

    def set_cache_rate(self, text: str) -> None:
        self.cache_label.configure(text=f"缓存命中：{text}")

    def refresh_history(self) -> None:
        page = self.pages.get("history")
        if page:
            page.refresh()

    def _enqueue_log(self, formatted: str, level: str) -> None:
        self.ui_queue.put({"type": "log", "text": formatted, "level": level})

    def _poll_queue(self) -> None:
        while True:
            try:
                msg = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if msg.get("type") == "log":
                self.log_panel.append(str(msg.get("text") or ""), str(msg.get("level") or "INFO"), raw=True)
                continue
            job_id = msg.get("job_id")
            routed = False
            page = self.pages.get("analysis")
            if page is not None and job_id and getattr(page, "job_id", None) == job_id:
                page.handle_message(msg)
                routed = True
            if not routed:
                target = msg.get("target") or msg.get("page") or "analysis"
                page = self.pages.get(target) or self.pages["analysis"]
                page.handle_message(msg)
        first = self.credentials.all()[0] if self.credentials.all() else None
        snapshot = first.limiter.snapshot() if first else self.limiter.snapshot()
        safety_mode = "独立 Key"
        try:
            from app.api.scheduler import MODE_SHARED

            # 若当前页有 client 则无法直接读；用凭据 429 近似
            hot = sum(1 for c in self.credentials.all() if c.count_429)
            if hot >= 2:
                safety_mode = "检测到共享限制"
        except Exception:
            pass
        self.limit_label.configure(text=f"限频：{snapshot.display} · {safety_mode}")
        self.after(80, self._poll_queue)


def run_app() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    app = MainWindow()
    app.mainloop()
