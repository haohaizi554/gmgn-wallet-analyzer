from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

import customtkinter as ctk

from app.gui.theme import MUTED, PANEL, PRIMARY, TEXT, font
from app.gui.ui_scheduler import row_identity


class DataTable(ctk.CTkFrame):
    def __init__(
        self,
        master,
        columns: list[tuple[str, str, int]],
        on_copy: Optional[Callable[[str], None]] = None,
        **kwargs,
    ):
        super().__init__(master, fg_color=PANEL, **kwargs)
        self.columns = columns
        self.on_copy = on_copy
        self._full_values: dict[str, str] = {}
        self._filter_job: str | None = None
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=8, pady=(8, 4))
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="全部")
        ctk.CTkLabel(toolbar, text="搜索", font=font(12), text_color=MUTED).pack(side="left")
        entry = ctk.CTkEntry(toolbar, textvariable=self.search_var, width=220, height=28)
        entry.pack(side="left", padx=8)
        entry.bind("<KeyRelease>", lambda _e: self._schedule_filter())
        self.filter_box = ctk.CTkComboBox(toolbar, variable=self.filter_var, values=["全部"], width=140, height=28, command=lambda _v: self.apply_filter())
        self.filter_box.pack(side="left", padx=8)
        self.count_label = ctk.CTkLabel(toolbar, text="0 行", font=font(12), text_color=MUTED)
        self.count_label.pack(side="right")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("GMGN.Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground=TEXT, rowheight=26, font=("Microsoft YaHei UI", 9))
        style.configure("GMGN.Treeview.Heading", background="#CCFBF1", foreground=TEXT, font=("Microsoft YaHei UI", 9, "bold"), relief="flat")
        style.map("GMGN.Treeview", background=[("selected", PRIMARY)], foreground=[("selected", "#FFFFFF")])

        container = ctk.CTkFrame(self, fg_color=PANEL)
        container.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tree = ttk.Treeview(container, columns=[c[0] for c in columns], show="headings", style="GMGN.Treeview")
        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        for key, title, width in columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w")
        self.tree.tag_configure("profit", foreground="#15803D")
        self.tree.tag_configure("loss", foreground="#B91C1C")
        self.tree.tag_configure("special", foreground="#C2410C")
        self.tree.bind("<Double-1>", self._copy_cell)
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="复制单元格", command=self._copy_selected)
        self.menu.add_command(label="复制完整地址/哈希", command=self._copy_full)
        self.tree.bind("<Button-3>", self._popup)
        self._rows: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}

    def set_filters(self, values: list[str]) -> None:
        current = self.filter_var.get()
        self.filter_box.configure(values=values)
        if current in values:
            self.filter_var.set(current)
        else:
            self.filter_var.set("全部")

    def set_rows(self, rows: list[dict[str, Any]], full_map: Optional[dict[str, str]] = None) -> None:
        self._rows = rows
        self._full_values = full_map or {}
        self._by_id = {row_identity(row, idx): row for idx, row in enumerate(rows)}
        self._sync_tree()

    def upsert_row(self, row: dict[str, Any]) -> None:
        iid = row_identity(row)
        if not iid:
            return
        current = dict(self._by_id.get(iid) or {})
        current.update(row)
        current.setdefault("_id", iid)
        self._by_id[iid] = current
        replaced = False
        for idx, existing in enumerate(self._rows):
            if row_identity(existing, idx) == iid:
                self._rows[idx] = current
                replaced = True
                break
        if not replaced:
            self._rows.append(current)
        if not self._row_visible(current):
            if self.tree.exists(iid):
                self.tree.delete(iid)
            self._update_count()
            return
        values = self._values(current)
        tags = self._tags(current)
        if self.tree.exists(iid):
            if self.tree.item(iid, "values") != values:
                self.tree.item(iid, values=values, tags=tags)
        else:
            self.tree.insert("", "end", iid=iid, values=values, tags=tags)
        self._update_count()

    def row_by_id(self, iid: str) -> Optional[dict[str, Any]]:
        return self._by_id.get(iid)

    def _schedule_filter(self) -> None:
        if self._filter_job is not None:
            try:
                self.after_cancel(self._filter_job)
            except Exception:
                pass
        self._filter_job = self.after(150, self.apply_filter)

    def apply_filter(self) -> None:
        self._filter_job = None
        self._sync_tree()

    def _row_visible(self, row: dict[str, Any]) -> bool:
        filt = self.filter_var.get()
        if filt != "全部" and str(row.get("_filter") or row.get("类型") or row.get("状态") or "") != filt and filt not in str(row.get("_filters") or ""):
            return False
        keyword = self.search_var.get().strip().lower()
        if keyword:
            hay = " ".join(str(v) for v in row.values()).lower()
            if keyword not in hay:
                return False
        return True

    def _values(self, row: dict[str, Any]) -> tuple:
        out = []
        for col in self.columns:
            value = row.get(col[0], "")
            out.append("" if value is None else str(value))
        return tuple(out)

    def _tags(self, row: dict[str, Any]) -> tuple:
        tag = row.get("_tag")
        return (tag,) if tag else ()

    def _sync_tree(self) -> None:
        wanted: list[tuple[str, dict[str, Any]]] = []
        for idx, row in enumerate(self._rows):
            if not self._row_visible(row):
                continue
            wanted.append((row_identity(row, idx), row))
        existing = list(self.tree.get_children(""))
        existing_set = set(existing)
        wanted_ids = [iid for iid, _ in wanted]
        wanted_set = set(wanted_ids)
        selected = [iid for iid in self.tree.selection() if iid in wanted_set]
        try:
            y0 = self.tree.yview()[0]
        except Exception:
            y0 = 0.0
        for iid in existing:
            if iid not in wanted_set:
                self.tree.delete(iid)
        for iid, row in wanted:
            values = self._values(row)
            tags = self._tags(row)
            if iid in existing_set:
                current = self.tree.item(iid, "values")
                if current != values:
                    self.tree.item(iid, values=values, tags=tags)
            else:
                self.tree.insert("", "end", iid=iid, values=values, tags=tags)
        for idx, (iid, _) in enumerate(wanted):
            self.tree.move(iid, "", idx)
        self._update_count(len(wanted))
        if selected:
            self.tree.selection_set(selected)
        try:
            self.tree.yview_moveto(y0)
        except Exception:
            pass

    def _update_count(self, shown: Optional[int] = None) -> None:
        if shown is None:
            shown = len(self.tree.get_children(""))
        text = f"{shown} 行"
        if self.count_label.cget("text") != text:
            self.count_label.configure(text=text)

    def _popup(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.menu.tk_popup(event.x_root, event.y_root)

    def _copy_cell(self, _event=None) -> None:
        self._copy_selected()

    def _copy_selected(self) -> None:
        item = self.tree.focus()
        if not item:
            return
        values = self.tree.item(item, "values")
        if values:
            self.clipboard_clear()
            self.clipboard_append("\t".join(str(v) for v in values))

    def _copy_full(self) -> None:
        item = self.tree.focus()
        if not item:
            return
        row = self._by_id.get(item)
        if row is None:
            return
        full = row.get("_copy") or row.get("代币合约") or row.get("TxHash") or ""
        self.clipboard_clear()
        self.clipboard_append(str(full))
        if self.on_copy:
            self.on_copy(str(full))
