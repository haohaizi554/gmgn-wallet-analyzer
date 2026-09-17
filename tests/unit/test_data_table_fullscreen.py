from __future__ import annotations

import unittest

import customtkinter as ctk

from app.gui.analysis_page import AnalysisPage
from app.gui.components.data_table import DataTable
from app.gui.theme import apply_theme


class DataTableFullscreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        apply_theme()
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()

    def test_fullscreen_keeps_toolbar_and_restores(self) -> None:
        host = ctk.CTkFrame(self.root)
        host.pack(fill="both", expand=True)
        table = DataTable(host, [("time", "时间", 120), ("type", "类型", 80)])
        table.pack(fill="both", expand=True, padx=12, pady=12)
        table.set_filters(["全部", "buy", "sell"])
        table.set_rows(
            [
                {"_id": "1", "time": "2026-09-18", "type": "buy", "_filter": "buy"},
                {"_id": "2", "time": "2026-09-18", "type": "sell", "_filter": "sell"},
            ]
        )
        self.root.update_idletasks()

        self.assertIsNotNone(table._fs_btn)
        self.assertEqual(table._fs_btn.cget("text"), "全屏")

        table.enter_fullscreen()
        self.root.update_idletasks()
        self.assertTrue(table._is_fullscreen)
        self.assertIsNotNone(table._fs_overlay)
        self.assertIsNotNone(table._fs_peer)
        peer = table._fs_peer
        assert peer is not None
        self.assertEqual(peer._fs_btn.cget("text"), "退出全屏")
        self.assertEqual(peer.count_label.cget("text"), table.count_label.cget("text"))
        self.assertEqual(list(peer.filter_box.cget("values")), ["全部", "buy", "sell"])

        peer.search_var.set("buy")
        self.root.update_idletasks()
        self.assertEqual(table.search_var.get(), "buy")

        table.exit_fullscreen()
        self.root.update_idletasks()
        self.assertFalse(table._is_fullscreen)
        self.assertIsNone(table._fs_overlay)
        self.assertEqual(table._fs_btn.cget("text"), "全屏")
        self.assertEqual(table.search_var.get(), "buy")
        self.assertEqual(str(table.winfo_manager()), "pack")

        host.destroy()

    def test_wallet_table_can_disable_fullscreen(self) -> None:
        table = DataTable(self.root, [("wallet", "钱包", 80)], allow_fullscreen=False)
        table.pack()
        self.root.update_idletasks()
        self.assertIsNone(table._fs_btn)
        table.destroy()

    def test_callback_does_not_open_overlay(self) -> None:
        called = []
        table = DataTable(self.root, [("type", "类型", 80)], on_fullscreen=lambda: called.append(True))
        table.pack()
        self.root.update_idletasks()
        table._fs_btn.invoke()
        self.assertEqual(called, [True])
        self.assertIsNone(table._fs_overlay)
        table.destroy()

    def test_analysis_page_keeps_tabs_and_toolbar(self) -> None:
        class FakeCreds:
            def snapshot(self):
                return []

        class FakeApp:
            credentials = FakeCreds()
            sidebar = None
            log_panel = None
            status = None

            def set_key_status(self, *_a, **_k):
                pass

        page = AnalysisPage(self.root, FakeApp())
        page.pack(fill="both", expand=True)
        self.root.update_idletasks()
        page.toggle_results_fullscreen()
        self.root.update_idletasks()
        self.assertTrue(page._results_fullscreen)
        self.assertEqual(page._left_panel.winfo_manager(), "")
        self.assertEqual(page._tabs.winfo_manager(), "pack")
        self.assertEqual(page.trade_table._fs_btn.cget("text"), "退出全屏")
        page.toggle_results_fullscreen()
        self.root.update_idletasks()
        self.assertFalse(page._results_fullscreen)
        self.assertEqual(page._left_panel.winfo_manager(), "pack")
        self.assertEqual([str(w) for w in page.pack_slaves()], [str(page._left_panel), str(page._right_panel)])
        self.assertEqual(
            [str(w) for w in page._right_panel.pack_slaves()],
            [str(page._card_row), str(page.wallet_table), str(page._tabs)],
        )
        page.destroy()


if __name__ == "__main__":
    unittest.main()
