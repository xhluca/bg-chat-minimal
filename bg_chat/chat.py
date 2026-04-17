"""Two chat UI variants:
- OverlayChat: a Chromium extension that injects a fixed-position chat panel
  into every page the agent visits (single window, side-by-side).
- WindowChat: a separate browser window dedicated to the chat panel
  (two windows, original BrowserGym-style layout).
The factory ``make_chat(ui, ...)`` picks one based on the user's choice."""

import hashlib
import json
import logging
import os
import tempfile
import time
from importlib import resources
from pathlib import Path
from typing import Literal

import playwright.sync_api

from . import _get_global_playwright, extension as extension_pkg, chat_files

logger = logging.getLogger(__name__)

EXTENSION_DIR = Path(str(resources.files(extension_pkg)))
CHATBOX_DIR = resources.files(chat_files)


def _compute_extension_id(path: str) -> str:
    """Chrome's deterministic ID for unpacked extensions: first 16 bytes of
    SHA256(path), mapped 0->a..f->p."""
    h = hashlib.sha256(path.encode()).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in h)


def _seed_pinned_extension(user_data_dir: str, extension_id: str):
    """Pre-write the Default profile's Preferences file so the extension
    appears as a pinned toolbar icon by default."""
    profile_dir = os.path.join(user_data_dir, "Default")
    os.makedirs(profile_dir, exist_ok=True)
    prefs_path = os.path.join(profile_dir, "Preferences")
    prefs = {"extensions": {"pinned_extensions": [extension_id]}}
    with open(prefs_path, "w") as f:
        json.dump(prefs, f)


class OverlayChat:
    """Owns the persistent browser context and exposes hooks the agent uses to
    drive the overlay chat UI. The overlay is re-injected on every navigation
    by the extension's content script; ``self.page`` follows whichever page
    the agent is currently on, and ``main_page`` is the initial tab."""

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
        ext_path = str(EXTENSION_DIR.resolve())

        # Pin the extension to the toolbar by default by seeding Chrome's
        # Preferences file with our deterministic extension ID before launch.
        _seed_pinned_extension(self._user_data_dir, _compute_extension_id(ext_path))

        # Extensions require a non-headless persistent context. bypass_csp
        # disables page-level Content Security Policy enforcement (including
        # Trusted Types) so Playwright's page.evaluate() works on locked-down
        # sites like Google's, and so the overlay's injected script isn't
        # blocked.
        self.context = pw.chromium.launch_persistent_context(
            user_data_dir=self._user_data_dir,
            headless=False,
            viewport={"width": viewport_width, "height": viewport_height},
            record_video_dir=record_video_dir,
            bypass_csp=True,
            args=[
                f"--disable-extensions-except={ext_path}",
                f"--load-extension={ext_path}",
            ],
        )

        # Expose the user-message bridge to every page in the context — the
        # overlay is re-injected on each navigation and immediately uses it.
        self.context.expose_function(
            "send_user_message", lambda msg: self._on_user_message(msg)
        )

        # The persistent context opens a default tab.
        self.main_page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page = self.main_page

        # Re-render the chat history into the freshly-injected overlay every
        # time the active page navigates.
        def _on_load():
            try:
                self.wait_for_overlay(timeout_s=5)
                self.replay_messages()
            except Exception as e:
                logger.debug("Overlay re-render failed: %s", e)

        self.main_page.on("load", lambda _: _on_load())

    # In overlay mode the chat sits on the right edge of every page, so
    # the agent should crop screenshots to exclude that area.
    PANEL_WIDTH = 400
    screenshot_crop_right = PANEL_WIDTH

    def attach_to(self, page):
        """Switch the chat to drive a different page (after navigation, etc.).
        The overlay's content script auto-injects on every navigation, so this
        only needs to be called when the agent moves to a different tab."""
        self.page = page

    def wait_for_overlay(self, timeout_s: float = 10):
        """Block until the overlay is ready on the current page. Used after
        navigation since the overlay re-injects from scratch each time."""
        try:
            self.page.wait_for_function(
                "window.__bgChatReady === true",
                polling=100, timeout=timeout_s * 1000,
            )
            return True
        except Exception:
            return False

    def replay_messages(self):
        """Re-render all stored messages into a freshly-injected overlay."""
        for m in self.messages:
            ts = time.strftime("%H:%M:%S", time.localtime(m.get("timestamp", time.time())))
            self._call_js("addChatMessage", m["role"], ts, m["message"])

    def _call_js(self, fn, *args):
        """Call a global JS function with positional args, JSON-encoded."""
        import json
        payload = ", ".join(json.dumps(a) for a in args)
        try:
            self.page.evaluate(f"{fn}({payload})")
        except Exception as e:
            logger.debug("JS call %s failed: %s", fn, e)

    def _on_user_message(self, msg: str):
        utc_time = time.time()
        self.messages.append({"role": "user", "timestamp": utc_time, "message": msg})
        return ["user", time.strftime("%H:%M", time.localtime(utc_time)), msg]

    def add_message(self, role: Literal["user", "assistant", "info", "infeasible", "think"], msg: str):
        utc_time = time.time()
        if role in ("user", "assistant", "infeasible"):
            self.messages.append({"role": role, "timestamp": utc_time, "message": msg})
        timestamp = time.strftime("%H:%M:%S", time.localtime(utc_time))
        self._call_js("addChatMessage", role, timestamp, msg)

    def start_streaming_think(self):
        self._call_js("startStreamingThink")

    def append_streaming_token(self, token: str):
        self._call_js("appendStreamingToken", token)

    def finalize_streaming_think(self):
        self._call_js("finalizeStreamingThink")

    def wait_for_user_message(self) -> bool:
        """Block until the user sends a message or signals end. Returns True if
        a real message was received, False if the session was ended."""
        logger.info("Waiting for message from user...")
        try:
            self.page.evaluate("window.USER_MESSAGE_RECEIVED = false;")
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
            return bool(self.page.evaluate("window.AGENT_PAUSED"))
        except Exception:
            return False

    @property
    def should_end(self) -> bool:
        try:
            return bool(self.page.evaluate("window.AGENT_END"))
        except Exception:
            return True

    def wait_while_paused(self):
        if self.is_paused:
            logger.info("Agent paused, waiting for resume...")
            try:
                self.page.wait_for_function(
                    "!window.AGENT_PAUSED", polling=200, timeout=0,
                )
            except Exception:
                pass
            logger.info("Agent resumed.")

    def close(self):
        try:
            self.context.close()
        except Exception:
            pass


class WindowChat:
    """Two-window variant: the chat lives in its own Chromium window, the
    agent drives a separate window for browsing. Same external API as
    OverlayChat so the agent loop can use either interchangeably."""

    def __init__(
        self,
        headless: bool,
        viewport_width: int = 1280,
        viewport_height: int = 720,
        chat_size=(400, 800),
        record_video_dir=None,
    ):
        self.messages = []

        pw: playwright.sync_api.Playwright = _get_global_playwright()

        # Agent's browser
        self._agent_browser = pw.chromium.launch(headless=headless)
        self.context = self._agent_browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
        )
        self.main_page = self.context.new_page()
        self.page = self.main_page  # parity with OverlayChat naming

        # Chat panel browser
        self._chat_browser = pw.chromium.launch(
            headless=headless,
            args=[f"--window-size={chat_size[0]},{chat_size[1]}"],
        )
        self._chat_context = self._chat_browser.new_context(
            no_viewport=True,
            record_video_dir=Path(record_video_dir) / "chat_video" if record_video_dir else None,
            record_video_size=dict(width=chat_size[0], height=chat_size[1]),
        )
        self._chat_page = self._chat_context.new_page()
        self._chat_page.expose_function(
            "send_user_message", lambda msg: self._on_user_message(msg)
        )
        html = (CHATBOX_DIR / "chatbox_modern.html").read_text()
        self._chat_page.set_content(html)

    # In window mode the agent's browser doesn't have any chat overlay, so
    # screenshots can use the full viewport.
    screenshot_crop_right = 0

    # --- API parity with OverlayChat ---

    def attach_to(self, page):
        self.page = page

    def wait_for_overlay(self, timeout_s: float = 10):
        return True

    def replay_messages(self):
        # Two-window mode: chat panel persists, no need to replay.
        return

    def _on_user_message(self, msg: str):
        utc_time = time.time()
        self.messages.append({"role": "user", "timestamp": utc_time, "message": msg})
        return ["user", time.strftime("%H:%M", time.localtime(utc_time)), msg]

    def add_message(self, role, msg: str):
        utc_time = time.time()
        if role in ("user", "assistant", "infeasible"):
            self.messages.append({"role": role, "timestamp": utc_time, "message": msg})
        timestamp = time.strftime("%H:%M:%S", time.localtime(utc_time))
        try:
            self._chat_page.evaluate(
                f"addChatMessage({json.dumps(role)}, {json.dumps(timestamp)}, {json.dumps(msg)});"
            )
        except Exception as e:
            logger.debug("WindowChat add_message failed: %s", e)

    def start_streaming_think(self):
        try:
            self._chat_page.evaluate("startStreamingThink();")
        except Exception:
            pass

    def append_streaming_token(self, token: str):
        try:
            self._chat_page.evaluate(f"appendStreamingToken({json.dumps(token)});")
        except Exception:
            pass

    def finalize_streaming_think(self):
        try:
            self._chat_page.evaluate("finalizeStreamingThink();")
        except Exception:
            pass

    def wait_for_user_message(self) -> bool:
        logger.info("Waiting for message from user...")
        try:
            self._chat_page.evaluate("USER_MESSAGE_RECEIVED = false;")
            self._chat_page.wait_for_function(
                "USER_MESSAGE_RECEIVED || AGENT_END", polling=100, timeout=0,
            )
            return bool(self._chat_page.evaluate("USER_MESSAGE_RECEIVED"))
        except Exception:
            return False

    @property
    def is_paused(self) -> bool:
        try:
            return bool(self._chat_page.evaluate("AGENT_PAUSED"))
        except Exception:
            return False

    @property
    def should_end(self) -> bool:
        try:
            return bool(self._chat_page.evaluate("AGENT_END"))
        except Exception:
            return True

    def wait_while_paused(self):
        if self.is_paused:
            try:
                self._chat_page.wait_for_function(
                    "!AGENT_PAUSED", polling=200, timeout=0,
                )
            except Exception:
                pass

    def close(self):
        for closer in (self._chat_context.close, self._chat_browser.close,
                       self.context.close, self._agent_browser.close):
            try:
                closer()
            except Exception:
                pass


def make_chat(ui: str, **kwargs):
    """Factory that returns the appropriate Chat implementation."""
    if ui == "overlay":
        # Filter to OverlayChat's expected kwargs
        accepted = {k: v for k, v in kwargs.items()
                    if k in ("headless", "viewport_width", "viewport_height", "record_video_dir")}
        return OverlayChat(**accepted)
    elif ui == "window":
        accepted = {k: v for k, v in kwargs.items()
                    if k in ("headless", "viewport_width", "viewport_height", "record_video_dir")}
        return WindowChat(**accepted)
    raise ValueError(f"Unknown UI mode: {ui!r}. Choose 'overlay' or 'window'.")


# Backwards-compatible alias
Chat = OverlayChat
