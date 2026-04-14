"""Chat panel: a separate browser window with a chat UI."""

import logging
import time
from importlib import resources
from pathlib import Path
from typing import Literal

import playwright.sync_api

from . import _get_global_playwright, chat_files

logger = logging.getLogger(__name__)

CHATBOX_DIR = resources.files(chat_files)


class Chat:
    def __init__(self, headless: bool, chat_size=(500, 800), record_video_dir=None):
        self.messages = []

        pw: playwright.sync_api.Playwright = _get_global_playwright()
        self.browser = pw.chromium.launch(
            headless=headless, args=[f"--window-size={chat_size[0]},{chat_size[1]}"]
        )
        self.context = self.browser.new_context(
            no_viewport=True,
            record_video_dir=Path(record_video_dir) / "chat_video" if record_video_dir else None,
            record_video_size=dict(width=chat_size[0], height=chat_size[1]),
        )
        self.page = self.context.new_page()

        self.page.expose_function(
            "send_user_message", lambda msg: self._on_user_message(msg)
        )

        html = (CHATBOX_DIR / "chatbox_modern.html").read_text()
        self.page.set_content(html)

    def _on_user_message(self, msg: str):
        utc_time = time.time()
        self.messages.append({"role": "user", "timestamp": utc_time, "message": msg})
        return ["user", time.strftime("%H:%M", time.localtime(utc_time)), msg]

    def add_message(self, role: Literal["user", "assistant", "info", "infeasible"], msg: str):
        utc_time = time.time()
        if role in ("user", "assistant", "infeasible"):
            self.messages.append({"role": role, "timestamp": utc_time, "message": msg})
        timestamp = time.strftime("%H:%M:%S", time.localtime(utc_time))
        self.page.evaluate(f"addChatMessage({repr(role)}, {repr(timestamp)}, {repr(msg)});")

    def wait_for_user_message(self):
        logger.info("Waiting for message from user...")
        self.page.evaluate("USER_MESSAGE_RECEIVED = false;")
        self.page.wait_for_function("USER_MESSAGE_RECEIVED", polling=100, timeout=0)
        logger.info("Message received.")

    def close(self):
        self.context.close()
        self.browser.close()
