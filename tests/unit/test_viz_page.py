from __future__ import annotations

import unittest

import customtkinter as ctk

from app.gui.theme import apply_theme
from app.gui.viz_page import VizPage


class VizPageGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        apply_theme()
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()

    def test_grid_is_not_shadowed_by_report_options(self) -> None:
        class FakeApp:
            pages = {}
            db_repos = None

        host = ctk.CTkFrame(self.root)
        host.grid_rowconfigure(0, weight=1)
        host.grid_columnconfigure(0, weight=1)
        page = VizPage(host, FakeApp())
        page.grid(row=0, column=0, sticky="nsew")
        self.root.update_idletasks()
        self.assertTrue(callable(page._options))
        self.assertEqual(page._report_options, [])
        page.destroy()
        host.destroy()


if __name__ == "__main__":
    unittest.main()
