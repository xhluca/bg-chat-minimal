"""Minimal agent loop: observe page, ask LLM, execute action, repeat."""

import json
import logging
import re

from openai import OpenAI

from .actions import (
    click, fill, go_back, goto, keyboard_press, scroll, describe_actions,
)
from .observation import (
    _pre_extract, _post_extract, extract_merged_axtree, extract_focused_element_bid,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a web agent that helps users accomplish tasks in a browser.

You can see the page's accessibility tree (AXTree) and must respond with exactly ONE action per turn.

# Available actions
{actions}

# Response format
You MUST respond in this exact format:

<think>
Your reasoning about what to do next.
</think>

<action>
one_action_call_here()
</action>

Only output ONE action per turn. Do NOT output multiple actions.
"""

def _format_axtree_node(node, depth=0) -> str:
    """Format a single AXTree node as indented text."""
    role = node.get("role", {}).get("value", "")
    name = node.get("name", {}).get("value", "")
    bid = node.get("browsergym_id", "")

    # skip ignored nodes
    if role in ("none", "generic") and not name and not bid:
        return ""

    parts = []
    if bid:
        parts.append(f"[{bid}]")
    parts.append(role)
    if name:
        parts.append(f'"{name}"')

    # add properties
    for prop in node.get("properties", []):
        pname = prop["name"]
        pval = prop["value"].get("value", "")
        if pname in ("focused", "required", "checked") and pval:
            parts.append(f"{pname}")
        elif pname == "value" and pval:
            parts.append(f'value="{pval}"')

    indent = "  " * depth
    return f"{indent}{' '.join(parts)}"


def format_axtree(axtree: dict) -> str:
    """Convert a merged AXTree to a readable text representation."""
    # build parent-child map
    children_map = {}
    node_map = {}
    for node in axtree["nodes"]:
        nid = node["nodeId"]
        node_map[nid] = node
        for cid in node.get("childIds", []):
            children_map.setdefault(cid, [])
        children_map.setdefault(nid, [])

    for node in axtree["nodes"]:
        for cid in node.get("childIds", []):
            if cid in node_map:
                children_map[node["nodeId"]] = children_map.get(node["nodeId"], [])
                children_map[node["nodeId"]].append(cid)

    # find root (first node)
    if not axtree["nodes"]:
        return "(empty page)"

    lines = []

    def walk(nid, depth):
        node = node_map.get(nid)
        if not node:
            return
        line = _format_axtree_node(node, depth)
        if line.strip():
            lines.append(line)
        for cid in node.get("childIds", []):
            walk(cid, depth + 1)

    walk(axtree["nodes"][0]["nodeId"], 0)
    return "\n".join(lines[:500])  # cap at 500 lines


def get_observation(page) -> str:
    """Extract the page observation as formatted text."""
    _pre_extract(page, lenient=True)
    try:
        axtree = extract_merged_axtree(page)
        focused = extract_focused_element_bid(page)
    finally:
        _post_extract(page)

    url = page.url
    title = page.title()

    obs = f"# Current page\nURL: {url}\nTitle: {title}\n"
    if focused:
        obs += f"Focused element: [{focused}]\n"
    obs += f"\n# AXTree\n{format_axtree(axtree)}"
    return obs


def parse_action(response: str) -> str | None:
    """Extract the action from the LLM response."""
    match = re.search(r"<action>\s*(.*?)\s*</action>", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def execute_action(page, action_str: str, send_msg_to_user) -> bool:
    """Execute a parsed action string. Returns True if agent sent message to user."""
    sent_message = False

    def _send_msg_to_user(text):
        nonlocal sent_message
        send_msg_to_user(text)
        sent_message = True

    env = {
        "page": page,
        "click": lambda bid, **kw: click(page, bid, **kw),
        "fill": lambda bid, value, **kw: fill(page, bid, value, **kw),
        "go_back": lambda: go_back(page),
        "keyboard_press": lambda key: keyboard_press(page, key),
        "scroll": lambda bid, direction: scroll(page, bid, direction),
        "goto": lambda url: goto(page, url),
        "send_msg_to_user": _send_msg_to_user,
    }
    exec(action_str, env)
    return sent_message


def run_chat(
    base_url: str,
    model: str,
    start_url: str = "https://www.google.com",
    api_key: str = "EMPTY",
    temperature: float = 0.6,
    max_tokens: int = 4096,
    max_steps: int = 100,
    headless: bool = False,
    viewport_size: int = 720,
):
    """Run the interactive chat agent loop.

    Args:
        base_url: vLLM-compatible API endpoint URL.
        model: Model name served at the endpoint.
        start_url: Initial page to navigate to.
        api_key: API key (use "EMPTY" if none required).
        temperature: Sampling temperature.
        max_tokens: Max tokens per LLM response.
        max_steps: Maximum agent steps per user message.
        headless: Run browser in headless mode.
        viewport_size: Browser viewport size (square, 1:1 ratio).
    """
    from . import _get_global_playwright
    from .chat import Chat

    pw = _get_global_playwright()

    # LLM client
    client = OpenAI(base_url=base_url, api_key=api_key)

    # Browser
    browser = pw.chromium.launch(headless=headless)
    context = browser.new_context(
        viewport={"width": viewport_size, "height": viewport_size},
    )
    page = context.new_page()
    page.goto(start_url)
    page.wait_for_load_state("domcontentloaded")

    # Chat panel
    chat = Chat(headless=headless)
    chat.add_message("info", f"Connected to model: {model}")

    system_msg = SYSTEM_PROMPT.format(actions=describe_actions())
    conversation = [{"role": "system", "content": system_msg}]

    print(f"Agent running. Browser at {start_url}, model: {model}")
    print("Waiting for your message in the chat window...")

    try:
        while True:
            # Wait for user message
            chat.wait_for_user_message()
            user_msg = chat.messages[-1]["message"]

            if user_msg.strip().lower() in ("exit", "quit", "q"):
                chat.add_message("info", "Session ended.")
                break

            conversation.append({"role": "user", "content": user_msg})

            # Agent loop: keep going until agent sends a message back
            for step in range(max_steps):
                # Observe
                try:
                    obs = get_observation(page)
                except Exception as e:
                    obs = f"# Error extracting observation\n{e}"
                    logger.warning(f"Observation error: {e}")

                step_msg = f"# Observation (step {step + 1})\n{obs}"
                conversation.append({"role": "user", "content": step_msg})
                chat.add_message("info", f"Step {step + 1}: thinking...")

                # Ask LLM
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=conversation,
                        temperature=temperature,
                        max_completion_tokens=max_tokens,
                    )
                    reply = response.choices[0].message.content
                except Exception as e:
                    chat.add_message("info", f"LLM error: {e}")
                    logger.error(f"LLM error: {e}")
                    break

                conversation.append({"role": "assistant", "content": reply})

                # Parse and execute action
                action_str = parse_action(reply)
                if not action_str:
                    chat.add_message("info", "No action found in response.")
                    break

                chat.add_message("info", f"Action: {action_str}")

                try:
                    sent_message = execute_action(
                        page, action_str,
                        lambda text: chat.add_message("assistant", text),
                    )
                except Exception as e:
                    err = f"Action error: {e}"
                    chat.add_message("info", err)
                    conversation.append({"role": "user", "content": err})
                    continue

                page.wait_for_timeout(1000)

                # If agent sent a message, wait for next user input
                if sent_message:
                    break

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        chat.close()
        context.close()
        browser.close()
