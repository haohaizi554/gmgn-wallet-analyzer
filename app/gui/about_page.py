from __future__ import annotations

import customtkinter as ctk

from app.gui.theme import BG, MUTED, PANEL, TEXT, font
from app.version import APP_NAME, __version__


class AboutPage(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        scroll = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0)
        scroll.pack(fill="both", expand=True)
        card = ctk.CTkFrame(scroll, fg_color=PANEL)
        card.pack(fill="x", expand=True, padx=24, pady=24)
        ctk.CTkLabel(card, text=APP_NAME, font=font(22, "bold"), text_color=TEXT, anchor="w").pack(fill="x", padx=24, pady=(24, 8))
        text = (
            f"版本 {__version__}\n\n"
            "本工具是 Solana 钱包交易的多数据源可验证分析器。\n"
            "核心原则：准确、完整、可解释、可恢复、Excel 0 空字段。\n\n"
            "数据源：\n"
            "- Moralis：可选 Swap 主索引（需付费 Key；没有不影响分析）\n"
            "- Solana RPC：链上事实主路径与裁决（公共节点无需 Key）\n"
            "- DEX Screener：池子 / 市值 / FDV（无需 Key）\n"
            "- GMGN：辅助验证，不作为默认 history fallback\n"
            "- Helius：可选增强（RPC / 历史）；无 Key 时完全正常\n\n"
            "不使用 wallet_holdings（需要私钥签名）。\n"
            "不把 symbol 当主键；所有关联使用 (chain, mint)。\n"
            "首次买入由链上 blockTime 最终裁决。\n"
            "无法验证时输出明确语义，禁止用 0 伪装无数据。\n"
            "官方盈亏与本地 FIFO 分开保存。"
        )
        ctk.CTkLabel(card, text=text, justify="left", anchor="nw", font=font(14), text_color=MUTED).pack(fill="both", expand=True, padx=24, pady=(0, 24))
