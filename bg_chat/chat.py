"""Chat panel: a Chrome extension side panel loaded into the same browser as the agent."""

import hashlib
import logging
import tempfile
import time
from importlib import resources
from pathlib import Path
from typing import Literal

import playwright.sync_api

from . import _get_global_playwright, extension as extension_pkg

logger = logging.getLogger(__name__)

EXTENSION_DIR = Path(str(resources.files(extension_pkg)))


class Chat:
    def __init__(
        self,
        headless: bool,
        viewport_width: int = 1024,
        viewport_height: int = 720,
        record_video_dir=None,
    ):
        self.messages = []
        self._user_data_dir = tempfile.mkdtemp(prefix="bg-chat-userdata-")

        pw: playwright.sync_api.Playwright = _get_global_playwright()

        ext_path = str(EXTENSION_DIR)
        # Extensions require a non-headless persistent context.
        self.context = pw.chromium.launch_persistent_context(
            user_data_dir=self._user_data_dir,
            headless=False,
            viewport={"width": viewport_width, "height": viewport_height},
            record_video_dir=record_video_dir,
            args=[
                f"--disable-extensions-except={ext_path}",
                f"--load-extension={ext_path}",
            ],
        )

        # Expose the user-message bridge for ALL pages in this context — the
        # side panel page may load before or after this binding is attached.
        self.context.expose_function(
            "send_user_message", lambda msg: self._on_user_message(msg)
        )

        # The persistent context opens a default tab — that is the agent's
        # main browsing surface.
        self.main_page = self.context.pages[0] if self.context.pages else self.context.new_page()

        # Open the chat UI in a second tab using the extension's
        # chrome-extension:// URL. Chrome's actual side-panel API requires a
        # user gesture to open, which Playwright cannot provide, so we
        # instead use the extension page as a regular tab. Both tabs live in
        # the same browser window — the user can drag the chat tab to a new
        # window or use Chrome's split-view if they want it docked.
        ext_id = self._get_extension_id(timeout_s=10)
        self.page = self.context.new_page()
        self.page.goto(f"chrome-extension://{ext_id}/sidepanel.html")
        self.page.wait_for_load_state("domcontentloaded")
        # Keep the main browsing tab focused after the chat tab loads.
        try:
            self.main_page.bring_to_front()
        except Exception:
            pass

    def _get_extension_id(self, timeout_s: float):
        # Try to detect via service worker first.
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            for sw in self.context.service_workers:
                if sw.url.startswith("chrome-extension://"):
                    return sw.url.split("/")[2]
            time.sleep(0.2)
        # Fall back to Chrome's deterministic extension ID derived from the
        # extension's absolute path. Chrome computes this as the first 16
        # bytes of SHA256(path), with each hex char mapped 0->a..f->p.
        path = str(EXTENSION_DIR.resolve())
        h = hashlib.sha256(path.encode()).hexdigest()[:32]
        return "".join(chr(ord("a") + int(c, 16)) for c in h)

    def _on_user_message(self, msg: str):
        utc_time = time.time()
        self.messages.append({"role": "user", "timestamp": utc_time, "message": msg})
        return ["user", time.strftime("%H:%M", time.localtime(utc_time)), msg]

    def add_message(self, role: Literal["user", "assistant", "info", "infeasible", "think"], msg: str):
        utc_time = time.time()
        if role in ("user", "assistant", "infeasible"):
            self.messages.append({"role": role, "timestamp": utc_time, "message": msg})
        timestamp = time.strftime("%H:%M:%S", time.localtime(utc_time))
        self.page.evaluate(f"addChatMessage({repr(role)}, {repr(timestamp)}, {repr(msg)});")

    def start_streaming_think(self):
        self.page.evaluate("startStreamingThink();")

    def append_streaming_token(self, token: str):
        self.page.evaluate(f"appendStreamingToken({repr(token)});")

    def finalize_streaming_think(self):
        self.page.evaluate("finalizeStreamingThink();")

    def wait_for_user_message(self) -> bool:
        """Block until the user sends a message or signals end. Returns True if
        a real message was received, False if the session was ended."""
        logger.info("Waiting for message from user...")
        try:
            self.page.evaluate("USER_MESSAGE_RECEIVED = false;")
            self.page.wait_for_function(
                "window.USER_MESSAGE_RECEIVED || window.AGENT_END",
                polling=100, timeout=0,
            )
            return bool(self.page.evaluate("window.USER_MESSAGE_RECEIVED"))
        except Exception:
            return False

    @property
    def is_paused(self) -> bool:
        try:
            return self.page.evaluate("AGENT_PAUSED")
        except Exception:
            return False

    @property
    def should_end(self) -> bool:
        try:
            return self.page.evaluate("AGENT_END")
        except Exception:
            return True

    def wait_while_paused(self):
        if self.is_paused:
            logger.info("Agent paused, waiting for resume...")
            self.page.wait_for_function("!AGENT_PAUSED", polling=200, timeout=0)
            logger.info("Agent resumed.")

    def close(self):
        try:
            self.context.close()
        except Exception:
            pass
