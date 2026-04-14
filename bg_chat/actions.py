"""Minimal action primitives for web agents."""

from typing import Literal

import playwright.sync_api

from .constants import BROWSERGYM_ID_ATTRIBUTE as BID_ATTR


def get_elem_by_bid(page: playwright.sync_api.Page, bid: str) -> playwright.sync_api.Locator:
    """Locate an element by its browsergym ID, diving through nested frames."""
    if not isinstance(bid, str):
        raise ValueError(f"expected a string, got {repr(bid)}")

    current_frame = page
    i = 0
    while bid[i:] and not bid[i:].isnumeric():
        i += 1
        while bid[i:] and bid[i].isalpha() and bid[i].isupper():
            i += 1
        frame_bid = bid[:i]
        frame_elem = current_frame.get_by_test_id(frame_bid)
        if not frame_elem.count():
            raise ValueError(f'Could not find element with bid "{bid}"')
        current_frame = frame_elem.frame_locator(":scope")

    elem = current_frame.get_by_test_id(bid)
    if not elem.count():
        raise ValueError(f'Could not find element with bid "{bid}"')
    return elem


def click(page, bid: str, button: Literal["left", "middle", "right"] = "left", modifiers=None):
    """Click an element by bid."""
    elem = get_elem_by_bid(page, bid)
    try:
        elem.click(button=button, modifiers=modifiers or [], force=False, timeout=500)
    except playwright.sync_api.TimeoutError:
        elem.click(button=button, modifiers=modifiers or [], force=True, timeout=500)


def fill(page, bid: str, value: str):
    """Fill a form field by bid."""
    elem = get_elem_by_bid(page, bid)
    try:
        elem.fill(value, force=False, timeout=500)
    except playwright.sync_api.TimeoutError:
        elem.fill(value, force=True, timeout=500)


def go_back(page):
    """Navigate back."""
    page.go_back()


def keyboard_press(page, key: str):
    """Press a key or key combination."""
    page.keyboard.press(key)


def scroll(page, bid: str, direction: Literal["up", "down"]):
    """Scroll an element up or down."""
    elem = get_elem_by_bid(page, bid)
    delta = -3 if direction == "up" else 3
    elem.scroll_into_view_if_needed(timeout=500)
    elem.evaluate(f"el => el.scrollTop += {delta * 100}")


def goto(page, url: str):
    """Navigate to a URL."""
    page.goto(url)


# Action registry for parsing
ACTIONS = {
    "click": click,
    "fill": fill,
    "go_back": go_back,
    "keyboard_press": keyboard_press,
    "scroll": scroll,
    "goto": goto,
}


def describe_actions() -> str:
    """Return a text description of available actions for use in prompts."""
    return """\
click(bid: str, button: str = "left")
    Click an element. Examples: click('a51'), click('b22', button="right")

fill(bid: str, value: str)
    Fill a form field. Examples: fill('45', "search query")

go_back()
    Navigate to the previous page.

keyboard_press(key: str)
    Press a key. Examples: keyboard_press('Enter'), keyboard_press('ControlOrMeta+a')

scroll(bid: str, direction: str)
    Scroll element. Examples: scroll('42', 'down'), scroll('42', 'up')

goto(url: str)
    Navigate to URL. Examples: goto('https://www.google.com')

send_msg_to_user(text: str)
    Send a message to the user. Examples: send_msg_to_user("Here is the answer.")"""
