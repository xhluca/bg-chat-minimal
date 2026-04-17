"""CLI entry point for bg-chat."""

import argparse

from openai import OpenAI


def detect_model(base_url: str, api_key: str = "EMPTY") -> str:
    """Auto-detect the model name from the endpoint."""
    client = OpenAI(base_url=base_url, api_key=api_key)
    models = client.models.list()
    if models.data:
        return models.data[0].id
    raise RuntimeError(f"No models found at {base_url}")


def main():
    parser = argparse.ArgumentParser(
        description="Run a web agent in BrowserGym-style interactive chat mode",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--base-url", type=str, required=True, help="vLLM-compatible API endpoint")
    parser.add_argument("--model", type=str, default=None, help="Model name (auto-detected if omitted)")
    parser.add_argument("--start-url", type=str, default="about:blank", help="Starting URL")
    parser.add_argument("--api-key", type=str, default="EMPTY", help="API key")
    parser.add_argument("--temperature", type=float, default=0.6, help="Sampling temperature")
    parser.add_argument("--max-tokens", type=int, default=4096, help="Max tokens per response")
    parser.add_argument("--max-steps", type=int, default=100, help="Max agent steps per user message")
    parser.add_argument(
        "--ui", type=str, default="window", choices=["overlay", "window"],
        help="Chat UI: 'window' (chat in a separate Chromium window — default, recommended) "
             "or 'overlay' (chat injected into the page via a Chrome extension; experimental, "
             "may break on sites with strict CSP, custom layouts, or that conflict with the "
             "injected DOM)",
    )
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--viewport-width", type=int, default=None,
                        help="Viewport width in pixels (default: 1470 for overlay UI, 1070 for window UI)")
    parser.add_argument("--viewport-height", type=int, default=720, help="Viewport height in pixels")

    args = parser.parse_args()

    if args.model is None:
        print(f"Auto-detecting model from {args.base_url}...")
        args.model = detect_model(args.base_url, args.api_key)
        print(f"Detected model: {args.model}")

    from .agent import run_chat

    run_chat(
        base_url=args.base_url,
        model=args.model,
        start_url=args.start_url,
        api_key=args.api_key,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        max_steps=args.max_steps,
        headless=args.headless,
        viewport_width=args.viewport_width,
        viewport_height=args.viewport_height,
        ui=args.ui,
    )


if __name__ == "__main__":
    main()
