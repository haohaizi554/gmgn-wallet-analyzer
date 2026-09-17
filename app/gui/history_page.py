from __future__ import annotations

from datetime import datetime
from tkinter import messagebox
import os

import customtkinter as ctk

from app.gui.theme import BG, DANGER, MUTED, PANEL, TEXT, font
from app.utils.validators import short_address


class HistoryPage(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self.app = app
        ctk.CTkLabel(self, text="历史记录", font=font(20, "bold"), text_color=TEXT, anchor="w").pack(fill="x", padx=20, pady=(20, 8))
        ctk.CTkLabel(self, text="本地 SQLite 保存的分析报告，可打开 Excel / JSON。", font=font(13), text_color=MUTED, anchor="w").pack(fill="x", padx=20)
        self.listbox = ctk.CTkScrollableFrame(self, fg_color=PANEL)
        self.listbox.pack(fill="both", expand=True, padx=20, pady=16)
        self._dirty = True
        self._row_widgets: dict[str, ctk.CTkFrame] = {}
        self._header: ctk.CTkFrame | None = None
        self._empty: ctk.CTkLabel | None = None
        self.refresh()

    def mark_dirty(self) -> None:
        self._dirty = True

    def refresh_if_dirty(self) -> None:
        if self._dirty:
            self.refresh()

    def refresh(self) -> None:
        y0 = 0.0
        try:
            y0 = float(self.listbox._parent_canvas.yview()[0])  # type: ignore[attr-defined]
        except Exception:
            pass
        for child in self.listbox.winfo_children():
            child.destroy()
        self._row_widgets = {}
        self._header = None
        self._empty = None
        rows = self.app.db_repos.list_jobs(40)
        reports = self.app.db_repos.list_reports(40)
        if not rows and not reports:
            self._show_empty()
            self._dirty = False
            return
        self._ensure_header()
        for row in rows:
            created = datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M:%S") if row.get("created_at") else "-"
            summary = row.get("summary") or {}
            wallets = row.get("wallets") or []
            label = f"{row['job_id'][:8]} / {len(wallets)}钱包"
            excel = row.get("excel_path") or summary.get("excel_path") or ""
            self._add_row(
                row_id=f"job:{row['job_id']}",
                bg="#F9FAFB",
                created=created,
                label=label,
                kind="单钱包" if row.get("job_type") == "single" else "批量",
                status=str(row.get("status") or "-"),
                tokens=str(summary.get("token_count", "-")),
                excel=excel,
                json_path="",
                on_delete=lambda jid=row["job_id"]: self._delete_job(jid),
            )
        for row in reports:
            created = datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M:%S") if row.get("created_at") else "-"
            summary = row.get("summary") or {}
            self._add_row(
                row_id=f"report:{row['id']}",
                bg="#FFFFFF",
                created=created,
                label=short_address(row["wallet_address"]),
                kind=str(row.get("period") or "-"),
                status=str(row.get("status") or "-"),
                tokens=str(summary.get("token_count", "-")),
                excel=row.get("excel_path") or "",
                json_path=row.get("json_path") or "",
                on_delete=lambda rid=row["id"]: self._delete_report(rid),
            )
        self._dirty = False
        try:
            self.listbox._parent_canvas.yview_moveto(y0)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _ensure_header(self) -> None:
        if self._header is not None and self._header.winfo_exists():
            return
        if self._empty is not None:
            self._empty.destroy()
            self._empty = None
        header = ctk.CTkFrame(self.listbox, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(header, text="删除", width=70, anchor="e", font=font(12, "bold")).pack(side="right", padx=8)
        for col, w in [("时间", 160), ("Job / 钱包", 180), ("类型", 70), ("状态", 90), ("Token", 70), ("操作", 200)]:
            ctk.CTkLabel(header, text=col, width=w, anchor="w", font=font(12, "bold")).pack(side="left")
        self._header = header

    def _show_empty(self) -> None:
        if self._header is not None:
            self._header.destroy()
            self._header = None
        if self._empty is not None and self._empty.winfo_exists():
            return
        self._empty = ctk.CTkLabel(self.listbox, text="暂无历史报告", text_color=MUTED, font=font(14))
        self._empty.pack(pady=30)

    def _add_row(
        self,
        *,
        row_id: str,
        bg: str,
        created: str,
        label: str,
        kind: str,
        status: str,
        tokens: str,
        excel: str,
        json_path: str,
        on_delete,
    ) -> None:
        frame = ctk.CTkFrame(self.listbox, fg_color=bg)
        frame.pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(
            frame,
            text="删除",
            width=70,
            height=26,
            fg_color=DANGER,
            hover_color="#991B1B",
            command=on_delete,
        ).pack(side="right", padx=8, pady=6)
        ctk.CTkLabel(frame, text=created, width=160, anchor="w", font=font(12)).pack(side="left")
        ctk.CTkLabel(frame, text=label, width=180, anchor="w", font=font(12)).pack(side="left")
        ctk.CTkLabel(frame, text=kind, width=70, anchor="w", font=font(12)).pack(side="left")
        ctk.CTkLabel(frame, text=status, width=90, anchor="w", font=font(12)).pack(side="left")
        ctk.CTkLabel(frame, text=tokens, width=70, anchor="w", font=font(12)).pack(side="left")
        ctk.CTkButton(frame, text="打开 Excel", width=90, height=26, command=lambda p=excel: self._open(p)).pack(side="left", padx=4)
        if json_path:
            ctk.CTkButton(
                frame,
                text="打开 JSON",
                width=90,
                height=26,
                fg_color="#E5E7EB",
                text_color=TEXT,
                command=lambda p=json_path: self._open(p),
            ).pack(side="left")
        self._row_widgets[row_id] = frame

    def _drop_row(self, row_id: str) -> None:
        frame = self._row_widgets.pop(row_id, None)
        if frame is not None:
            frame.destroy()
        if not self._row_widgets:
            self._show_empty()

    def _delete_job(self, job_id: str) -> None:
        if not messagebox.askyesno("删除记录", "删除这条任务记录？此操作不可撤销。"):
            return
        try:
            self.app.db_repos.delete_job(job_id)
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc))
            return
        self._drop_row(f"job:{job_id}")
        self._dirty = False

    def _delete_report(self, report_id: str) -> None:
        if not messagebox.askyesno("删除记录", "删除这条报告记录？此操作不可撤销。"):
            return
        try:
            self.app.db_repos.delete_report(report_id)
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc))
            return
        self._drop_row(f"report:{report_id}")
        self._dirty = False

    def _open(self, path: str) -> None:
        if not path or not os.path.exists(path):
            messagebox.showwarning("文件不存在", path or "空路径")
            return
        os.startfile(path)
