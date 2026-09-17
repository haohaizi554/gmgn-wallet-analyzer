from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

import customtkinter as ctk

from app.gui.theme import MUTED, PANEL, PRIMARY, TEXT, font


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
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=8, pady=(8, 4))
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="全部")
        ctk.CTkLabel(toolbar, text="搜索", font=font(12), text_color=MUTED).pack(side="left")
        entry = ctk.CTkEntry(toolbar, textvariable=self.search_var, width=220, height=28)
        entry.pack(side="left", padx=8)
        entry.bind("<KeyRelease>", lambda _e: self.apply_filter())
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

    def set_filters(self, values: list[str]) -> None:
        self.filter_box.configure(values=values)
        self.filter_var.set("全部")

    def set_rows(self, rows: list[dict[str, Any]], full_map: Optional[dict[str, str]] = None) -> None:
        self._rows = rows
        self._full_values = full_map or {}
        self.apply_filter()

    def apply_filter(self) -> None:
        keyword = self.search_var.get().strip().lower()
        filt = self.filter_var.get()
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for idx, row in enumerate(self._rows):
            if filt != "全部" and str(row.get("_filter") or row.get("类型") or row.get("状态") or "") != filt and filt not in str(row.get("_filters") or ""):
                continue
            hay = " ".join(str(v) for v in row.values()).lower()
            if keyword and keyword not in hay:
                continue
            values = [row.get(col[0], "") for col in self.columns]
            tags = []
            tag = row.get("_tag")
            if tag:
                tags.append(tag)
            self.tree.insert("", "end", iid=str(idx), values=values, tags=tuple(tags))
            shown += 1
        self.count_label.configure(text=f"{shown} 行")

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
        row = self._rows[int(item)]
        full = row.get("_copy") or row.get("代币合约") or row.get("TxHash") or ""
        self.clipboard_clear()
        self.clipboard_append(str(full))
        if self.on_copy:
            self.on_copy(str(full))
