from __future__ import annotations

import customtkinter as ctk

from app.gui.theme import BG, MUTED, PANEL, TEXT, font
from app.version import APP_NAME, __version__


class AboutPage(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        card = ctk.CTkFrame(self, fg_color=PANEL)
        card.pack(fill="both", expand=True, padx=24, pady=24)
        ctk.CTkLabel(card, text=APP_NAME, font=font(22, "bold"), text_color=TEXT, anchor="w").pack(fill="x", padx=24, pady=(24, 8))
        text = (
            f"版本 {__version__}\n\n"
            "本工具通过 GMGN OpenAPI 分析 Solana 钱包交易。\n"
            "核心原则：准确、完整、可解释、可恢复、Excel 0 空字段。\n\n"
            "数据来源：\n"
            "- GET /v1/user/wallet_activity\n"
            "- GET /v1/user/wallet_stats\n"
            "- POST /v1/user/wallet_profits\n"
            "- GET /v1/token/info\n"
            "- GET /v1/token/pool_info\n\n"
            "不使用 wallet_holdings（需要私钥签名）。\n"
            "不把 symbol 当主键；所有关联使用 token_address。\n"
            "首次买入按完整 cursor 历史中 timestamp 最小的 Buy。\n"
            "GMGN 官方盈亏与本地 FIFO 分开保存。"
        )
        ctk.CTkLabel(card, text=text, justify="left", anchor="nw", font=font(14), text_color=MUTED).pack(fill="both", expand=True, padx=24, pady=(0, 24))
