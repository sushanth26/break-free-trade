"""Telegram Bot API sender. Alerts only. The token comes from .env and is never logged."""
from __future__ import annotations

import json
import os
import urllib.request


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None, dry_run: bool = False,
                 timeout: float = 5.0):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.dry_run = dry_run or not (self.token and self.chat_id)
        self.timeout = timeout
        self.sent: list[str] = []

    def send(self, text: str) -> bool:
        self.sent.append(text)
        if self.dry_run:
            print(text)
            return True
        body = json.dumps({"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/sendMessage", data=body,
                                     headers={"Content-Type": "application/json"})
        for _ in range(2):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.status == 200
            except Exception as e:  # never include the URL (it holds the token)
                err = type(e).__name__
        print(f"telegram send failed ({err})")
        return False
