from __future__ import annotations

import customtkinter as ctk

from app.gui.analysis_page import AnalysisPage
from app.gui.theme import BG, MUTED, TEXT, font


class BatchPage(AnalysisPage):
    """任务进度页：与钱包分析共用 JobEngine，按 job_id 路由，不再双播。"""

    def __init__(self, master, app, **kwargs):
        super().__init__(master, app, **kwargs)
        self.page_key = "batch"
        self.title_label.configure(text="任务进度")
        self.meta_label.configure(text="多钱包与单钱包走同一套 JobEngine。单钱包 = batch size 1。")
