"""Agent loop matching agentlab GenericAgent behavior."""

import logging
import re
import time

from openai import OpenAI

from .actions import describe_actions, click, fill, go_back, goto, keyboard_press, scroll
from .observation import _pre_extract, _post_extract, extract_merged_axtree, extract_focused_element_bid
from .axtree import flatten_axtree_to_str

logger = logging.getLogger(__name__)

# --- Prompts matching agentlab ---

SYSTEM_PROMPT = """\
You are an agent trying to solve a web task based on the content of the page and \
user instructions. You can interact with the page and explore, and send messages \
to the user. Each time you submit an action it will be sent to the browser and \
you will receive a new page."""

CHAT_INSTRUCTIONS = """\
# Instructions

You are a UI Assistant, your goal is to help the user perform tasks using a web browser. You can \
see the content of the page through the accessibility tree and you can interact with it using actions. \
You can also send messages to the user via send_msg_to_user.

Review the instructions from the user, the current state of the page and all other \
information to find the best possible next action to accomplish the task. Your answer \
will be interpreted and executed by a program, make sure to follow the formatting instructions.

## Chat messages:
{chat_messages}
"""

OBSERVATION_TEMPLATE = """\

## AXTree:
Note: [bid] is the unique alpha-numeric identifier of the element; use it for actions.
{axtree}
"""

HISTORY_TEMPLATE = """\
# History of interaction with the task:
{steps}
"""

HISTORY_STEP_TEMPLATE = """\
## step {i}
<action>
{action}
</action>
"""

ACTION_PROMPT = """\

# Action space:
{action_description}

Here is the description of the available actions:
{action_details}
"""

HINTS = """\

# Abstract Example

Here is an abstract version of the answer with description of the content of \
each tag. Make sure you follow this structure, but replace the content with your \
answer:

<think>
Think step by step. Describe what you see on the page and reason about the task, \
the current state and what to do next. If there was an error from the previous \
action, reflect on what went wrong and how to fix it.
</think>

<action>
One single action to be executed. You can only use one action at a time.
</action>

# Concrete Example

Here is a concrete example of how to format your answer.

<think>
From the current observation I see a search box. I need to type "cat" in \
the search box to find information about cats. I will use the fill action to \
input the text.
</think>

<action>
fill('a12', 'cat')
</action>
"""

BE_CAUTIOUS = """\

# BE CAUTIOUS
Carefully check the current action against your plan and the effect of the \
previous action. If something doesn't go as planned, pause, reflect and \
plan a new course of action. Pay attention to details and minor differences. \
If the same action keeps failing, try alternative approaches."""


# --- Observation extraction ---

def get_observation(page) -> dict:
    """Extract structured observation from page, matching agentlab format."""
    _pre_extract(page, lenient=True)
    try:
        axtree = extract_merged_axtree(page)
        focused = extract_focused_element_bid(page)
    finally:
        _post_extract(page)

    axtree_txt = flatten_axtree_to_str(
        axtree,
        with_visible=True,
        with_clickable=True,
        skip_generic=True,
        remove_redundant_static_text=True,
    )

    return {
        "url": page.url,
        "title": page.title(),
        "axtree_txt": axtree_txt,
        "focused_element_bid": focused,
        "last_action_error": None,
    }


# --- Prompt building ---

def format_chat_messages(messages) -> str:
    """Format chat messages with timestamps, matching agentlab ChatInstructions."""
    if not messages:
        return "(no messages yet)"
    lines = []
    for msg in messages:
        ts = msg.get("timestamp", time.time())
        utc = time.asctime(time.gmtime(ts))
        local = time.asctime(time.localtime(ts))
        lines.append(f" - [{msg['role']}] UTC Time: {utc} - Local Time: {local} - {msg['message']}")
    return "\n".join(lines)


def build_prompt(
    obs: dict,
    chat_messages: list,
    history_actions: list,
    last_action_error: str | None,
    action_description: str,
) -> str:
    """Build the human message prompt, matching agentlab MainPrompt structure."""
    parts = []

    # 1. Instructions with chat messages
    parts.append(CHAT_INSTRUCTIONS.format(
        chat_messages=format_chat_messages(chat_messages),
    ))

    # 2. Observation
    obs_str = OBSERVATION_TEMPLATE.format(axtree=obs["axtree_txt"])
    if obs["focused_element_bid"]:
        obs_str += f"\nFocused element: [{obs['focused_element_bid']}]\n"
    if last_action_error:
        obs_str += f"\n## Error from previous action:\n{last_action_error}\n"
    parts.append(obs_str)

    # 3. History (action history only, matching A3 flags)
    if history_actions:
        steps = []
        for i, action in enumerate(history_actions):
            steps.append(HISTORY_STEP_TEMPLATE.format(i=i, action=action))
        parts.append(HISTORY_TEMPLATE.format(steps="\n".join(steps)))

    # 4. Action description
    parts.append(ACTION_PROMPT.format(
        action_description="Note: you can only use one action per turn.",
        action_details=action_description,
    ))

    # 5. Hints (abstract + concrete examples)
    parts.append(HINTS)

    # 6. Be cautious
    parts.append(BE_CAUTIOUS)

    return "\n".join(parts)


# --- Response parsing (matching agentlab) ---

def parse_think(response: str) -> str | None:
    match = re.search(r"<think>\s*(.*?)\s*</think>", response, re.DOTALL)
    return match.group(1).strip() if match else None


def parse_action(response: str) -> str | None:
    match = re.search(r"<action>\s*(.*?)\s*</action>", response, re.DOTALL)
    return match.group(1).strip() if match else None


class ParseError(Exception):
    pass


def parse_response(response: str) -> dict:
    """Parse LLM response, matching agentlab parse_html_tags_raise behavior."""
    action = parse_action(response)
    if action is None:
        raise ParseError(
            "Missing the key <action> in the answer. "
            "You must wrap your action in <action> tags like: <action>click('a12')</action>"
        )
    return {
        "think": parse_think(response),
        "action": action,
    }


# --- Action execution ---

def execute_action(page, action_str: str, send_msg_to_user) -> bool:
    """Execute a parsed action string. Returns True if agent sent message to user."""
    sent_message = False

    def _send_msg(text):
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
        "send_msg_to_user": _send_msg,
    }
    exec(action_str, env)
    return sent_message


# --- Main loop ---

def run_chat(
    base_url: str,
    model: str,
    start_url: str = "https://www.google.com",
    api_key: str = "EMPTY",
    temperature: float = 0.6,
    max_tokens: int = 4096,
    max_steps: int = 100,
    max_retry: int = 4,
    headless: bool = False,
    viewport_width: int = 1024,
    viewport_height: int = 720,
):
    """Run the interactive chat agent loop.

    Matches agentlab GenericAgent behavior:
    - Same system prompt and observation formatting
    - Same AX tree string conversion (flatten_axtree_to_str)
    - Only last observation in prompt (not accumulated)
    - Action history as summarized steps
    - LLM retry on parse errors (up to max_retry)
    - Chat messages with timestamps
    """
    from . import _get_global_playwright
    from .chat import Chat

    pw = _get_global_playwright()
    client = OpenAI(base_url=base_url, api_key=api_key)

    # Browser
    # Set Playwright's test ID attribute to "bid" (browsergym marks elements with bid="...")
    pw.selectors.set_test_id_attribute("bid")

    browser = pw.chromium.launch(headless=headless)
    context = browser.new_context(
        viewport={"width": viewport_width, "height": viewport_height},
    )
    page = context.new_page()
    page.goto(start_url)
    page.wait_for_load_state("domcontentloaded")

    # Chat panel
    chat = Chat(headless=headless)
    chat.add_message("info", f"Connected to model: {model}")

    action_description = describe_actions()
    history_actions = []

    print(f"Agent running. Browser at {start_url}, model: {model}")
    print("Waiting for your message in the chat window...")

    try:
        while True:
            chat.wait_for_user_message()
            user_msg = chat.messages[-1]["message"]

            if user_msg.strip().lower() in ("exit", "quit", "q"):
                chat.add_message("info", "Session ended.")
                break

            last_action_error = None

            for step in range(max_steps):
                # Check pause/restart
                chat.wait_while_paused()
                if chat.should_restart:
                    chat.clear_restart()
                    history_actions.clear()
                    chat.add_message("info", "Agent restarted. Send a new message.")
                    break

                # 1. Observe (only current observation, not accumulated)
                try:
                    obs = get_observation(page)
                except Exception as e:
                    obs = {
                        "url": page.url,
                        "title": page.title(),
                        "axtree_txt": f"(error extracting observation: {e})",
                        "focused_element_bid": "",
                        "last_action_error": None,
                    }
                    logger.warning(f"Observation error: {e}")

                # 2. Build prompt (matching agentlab MainPrompt)
                human_msg = build_prompt(
                    obs=obs,
                    chat_messages=chat.messages,
                    history_actions=history_actions,
                    last_action_error=last_action_error,
                    action_description=action_description,
                )

                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": human_msg},
                ]

                chat.add_message("info", f"Step {step + 1}: thinking...")

                # 3. LLM call with streaming + retry on parse errors
                ans_dict = None
                for retry in range(max_retry):
                    try:
                        chat.start_streaming_think()
                        stream = client.chat.completions.create(
                            model=model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            stream=True,
                        )
                        reply = ""
                        for chunk in stream:
                            delta = chunk.choices[0].delta
                            # Thinking tokens: "reasoning" (vLLM) or "reasoning_content" (llama.cpp)
                            reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
                            if reasoning:
                                chat.append_streaming_token(reasoning)
                            if delta.content:
                                reply += delta.content
                        chat.finalize_streaming_think()
                        messages.append({"role": "assistant", "content": reply})
                        ans_dict = parse_response(reply)
                        break
                    except ParseError as e:
                        chat.finalize_streaming_think()
                        logger.info(f"Parse error (retry {retry + 1}/{max_retry}): {e}")
                        messages.append({"role": "assistant", "content": reply})
                        messages.append({"role": "user", "content": str(e)})
                        continue
                    except Exception as e:
                        chat.finalize_streaming_think()
                        chat.add_message("info", f"LLM error: {e}")
                        logger.error(f"LLM error: {e}")
                        break

                if ans_dict is None:
                    chat.add_message("info", "Failed to get valid response from LLM.")
                    break

                # 4. Show action (thinking was already streamed above)
                action_str = ans_dict["action"]
                chat.add_message("info", f"Action: {action_str}")

                # 5. Execute action
                last_action_error = None
                try:
                    sent_message = execute_action(
                        page, action_str,
                        lambda text: chat.add_message("assistant", text),
                    )
                except Exception as e:
                    last_action_error = str(e)
                    chat.add_message("info", f"Action error: {e}")
                    history_actions.append(action_str)
                    continue

                history_actions.append(action_str)
                page.wait_for_timeout(1000)

                if sent_message:
                    break

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        chat.close()
        context.close()
        browser.close()
