"""Minimal BrowserGym-based interactive chat mode for web agents."""

import playwright.sync_api

_PLAYWRIGHT = None


def _get_global_playwright():
    global _PLAYWRIGHT
    if not _PLAYWRIGHT:
        _PLAYWRIGHT = playwright.sync_api.sync_playwright().start()
    return _PLAYWRIGHT
