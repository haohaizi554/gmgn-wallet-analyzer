from __future__ import annotations

from app.gui.analysis_page import AnalysisPage


class BatchPage(AnalysisPage):
    """任务进度页：与钱包分析共用 JobEngine，按 job_id 路由，不再双播。"""

    def __init__(self, master, app, **kwargs):
        super().__init__(master, app, **kwargs)
        self.page_key = "batch"
        self.progress.update_progress("任务进度", 0, 0)
