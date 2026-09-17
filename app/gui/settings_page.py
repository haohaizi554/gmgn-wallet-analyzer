from __future__ import annotations

import threading
from tkinter import messagebox

import customtkinter as ctk

from app.api.exceptions import GMGNError
from app.api.gmgn_client import GMGNClient
from app.config import load_config, save_api_settings
from app.gui.theme import BG, MUTED, PANEL, TEXT, font


class SettingsPage(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self.app = app
        card = ctk.CTkFrame(self, fg_color=PANEL)
        card.pack(fill="x", padx=24, pady=24)
        ctk.CTkLabel(card, text="系统设置", font=font(20, "bold"), text_color=TEXT, anchor="w").pack(fill="x", padx=20, pady=(18, 6))
        ctk.CTkLabel(
            card,
            text="每个 GMGN API Key 拥有独立加权限流器。若短时间内多把 Key 同时 429，会自动判定可能存在 IP/账号共享限制并进入全局冷却。不要填写钱包私钥。",
            font=font(13),
            text_color=MUTED,
            anchor="w",
            wraplength=900,
        ).pack(fill="x", padx=20)

        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="x", padx=20, pady=12)
        ctk.CTkLabel(form, text="API Keys（一行一把）", font=font(13), text_color=TEXT).grid(row=0, column=0, sticky="nw", pady=8)
        self.keys_box = ctk.CTkTextbox(form, width=420, height=90, font=font(13))
        self.keys_box.grid(row=0, column=1, sticky="w", padx=8)
        self.keys_box.insert("1.0", "\n".join(app.config.api_keys or ([app.config.api_key] if app.config.api_key else [])))

        ctk.CTkLabel(form, text="Base URL", font=font(13), text_color=TEXT).grid(row=1, column=0, sticky="w", pady=8)
        self.base_var = ctk.StringVar(value=app.config.api_base)
        ctk.CTkEntry(form, textvariable=self.base_var, width=420).grid(row=1, column=1, sticky="w", padx=8)

        ctk.CTkLabel(form, text="套餐", font=font(13), text_color=TEXT).grid(row=2, column=0, sticky="w", pady=8)
        self.plan_var = ctk.StringVar(value=app.config.plan)
        ctk.CTkComboBox(form, variable=self.plan_var, values=["Free", "Plus", "Pro"], width=160, command=self._plan_changed).grid(row=2, column=1, sticky="w", padx=8)

        ctk.CTkLabel(form, text="服务端 Rate / Capacity", font=font(13), text_color=TEXT).grid(row=3, column=0, sticky="w", pady=8)
        cap = ctk.CTkFrame(form, fg_color="transparent")
        cap.grid(row=3, column=1, sticky="w", padx=8)
        self.rate_var = ctk.StringVar(value=str(int(app.config.rate)))
        self.cap_var = ctk.StringVar(value=str(int(app.config.capacity)))
        ctk.CTkEntry(cap, textvariable=self.rate_var, width=80).pack(side="left")
        ctk.CTkLabel(cap, text=" / ").pack(side="left")
        ctk.CTkEntry(cap, textvariable=self.cap_var, width=80).pack(side="left")
        ctk.CTkLabel(cap, text="  （每 Key；Free=5）", font=font(12), text_color=MUTED).pack(side="left")

        ctk.CTkLabel(form, text="目标利用率", font=font(13), text_color=TEXT).grid(row=4, column=0, sticky="w", pady=8)
        self.util_var = ctk.StringVar(value=self._util_label(app.config.target_utilization))
        ctk.CTkComboBox(form, variable=self.util_var, values=["保守 60%", "推荐 75%", "较高 80%"], width=160).grid(row=4, column=1, sticky="w", padx=8)

        ctk.CTkLabel(form, text="API Workers", font=font(13), text_color=TEXT).grid(row=5, column=0, sticky="w", pady=8)
        self.workers_var = ctk.StringVar(value=str(app.config.api_workers))
        ctk.CTkComboBox(form, variable=self.workers_var, values=["2", "3", "4", "6", "8"], width=160).grid(row=5, column=1, sticky="w", padx=8)

        self.key_table = ctk.CTkLabel(card, text=self._key_status_text(), font=font(12), text_color=MUTED, anchor="w", justify="left")
        self.key_table.pack(fill="x", padx=20)

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=(8, 20))
        ctk.CTkButton(btns, text="保存", width=100, command=self.save).pack(side="left")
        ctk.CTkButton(btns, text="测试连接", width=100, fg_color="#E5E7EB", text_color=TEXT, command=self.test).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="全部测试", width=100, fg_color="#E5E7EB", text_color=TEXT, command=self.test_all).pack(side="left")
        self.status = ctk.CTkLabel(btns, text="", font=font(13), text_color=MUTED)
        self.status.pack(side="left", padx=8)

    def _util_label(self, value: float) -> str:
        if value <= 0.62:
            return "保守 60%"
        if value >= 0.78:
            return "较高 80%"
        return "推荐 75%"

    def _util_value(self) -> float:
        text = self.util_var.get()
        if "60" in text:
            return 0.60
        if "80" in text:
            return 0.80
        return 0.75

    def _keys(self) -> list[str]:
        text = self.keys_box.get("1.0", "end")
        keys = []
        for line in text.replace(",", "\n").splitlines():
            item = line.strip()
            if item and item not in keys:
                keys.append(item)
        return keys

    def _key_status_text(self) -> str:
        lines = [
            f"每 Key 限额：{self.app.config.plan}  {int(self.app.config.rate)} weighted units/s",
            f"最大目标利用率：{int(self.app.config.target_utilization * 100)}%   初始：{int(getattr(self.app.config,'initial_utilization',0.6)*100)}%   Workers：{self.app.config.api_workers}",
            "短时间多 Key 同时 429 时自动降级为共享限制保护。",
        ]
        for item in self.app.credentials.snapshot():
            lines.append(
                f"{item['masked']}  {item['state']}  目标={int((item.get('utilization') or 0)*100)}%  请求={item['requests']}  429={item['429']}  inflight={item.get('inflight')}"
            )
        return "\n".join(lines)

    def _plan_changed(self, value: str) -> None:
        mapping = {"Free": ("5", "5"), "Plus": ("20", "20"), "Pro": ("50", "50")}
        rate, cap = mapping.get(value, ("5", "5"))
        self.rate_var.set(rate)
        self.cap_var.set(cap)

    def save(self) -> None:
        keys = self._keys()
        save_api_settings(
            keys[0] if keys else "",
            self.base_var.get().strip() or "https://openapi.gmgn.ai",
            self.plan_var.get(),
            float(self.rate_var.get() or 5),
            float(self.cap_var.get() or 5),
            api_keys=keys,
            target_utilization=self._util_value(),
            api_workers=int(self.workers_var.get() or 4),
        )
        self.app.reload_config()
        self.key_table.configure(text=self._key_status_text())
        self.status.configure(text="已保存到 .env")
        messagebox.showinfo("已保存", "API 配置已写入 .env。每个 Key 独立限流；共享限制会自动检测。")

    def test(self) -> None:
        self.save()
        self.status.configure(text="测试中…")

        def work():
            try:
                client = GMGNClient(
                    self.app.config.api_key,
                    self.app.config.api_base,
                    limiter=self.app.limiter,
                    credential_pool=self.app.credentials,
                )
                data = client.test_connection()
                self.after(0, lambda: self._test_ok(data))
            except GMGNError as exc:
                self.after(0, lambda: self._test_fail(str(exc)))
            except Exception as exc:
                self.after(0, lambda: self._test_fail(str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def test_all(self) -> None:
        self.save()
        self.status.configure(text="逐把 Key 测试中（经过全局限流）…")

        def work():
            errors = []
            from app.api.credential_pool import CredentialPool, mask_key

            for i, key in enumerate(self.app.config.api_keys, start=1):
                try:
                    pool = CredentialPool([key])
                    client = GMGNClient(key, self.app.config.api_base, limiter=self.app.limiter, credential_pool=pool)
                    client.test_connection()
                except Exception as exc:
                    errors.append(f"{mask_key(key, i)}: {exc}")
            if errors:
                self.after(0, lambda: self._test_fail("\n".join(errors)))
            else:
                self.after(0, lambda: self._test_ok({"keys": len(self.app.config.api_keys)}))

        threading.Thread(target=work, daemon=True).start()

    def _test_ok(self, data) -> None:
        self.status.configure(text="连接成功")
        self.key_table.configure(text=self._key_status_text())
        self.app.set_api_status("API 正常")
        messagebox.showinfo("测试连接", f"连接成功。\n{list(data)[:8] if isinstance(data, dict) else type(data)}")

    def _test_fail(self, message: str) -> None:
        self.status.configure(text="连接失败")
        self.app.set_api_status("API 异常")
        messagebox.showerror("测试连接失败", message)
