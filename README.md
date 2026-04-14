# bg-chat-minimal

Minimal interactive chat mode for web agents. Only depends on `playwright` and `openai`.

Extracted and simplified from [BrowserGym](https://github.com/ServiceNow/BrowserGym) — includes AX tree extraction, action primitives, and a chat panel UI.

## Installation

```bash
pip install "bg-chat-minimal @ git+https://github.com/xhluca/bg-chat-minimal.git"
playwright install chromium
```

## Usage

### CLI

```bash
bg-chat --base-url https://your-vllm-endpoint.com/v1
```

Options:

```
--base-url URL      vLLM-compatible API endpoint (required)
--model NAME        Model name (auto-detected if omitted)
--start-url URL     Starting page (default: https://www.google.com)
--api-key KEY       API key (default: EMPTY)
--temperature 0.6   Sampling temperature
--viewport-size N   Browser viewport, square 1:1 (default: 720)
--headless          Run browser without display
```

### Python API

```python
from bg_chat.agent import run_chat

run_chat(
    base_url="https://your-vllm-endpoint.com/v1",
    model="your-model-name",
    start_url="https://www.google.com",
    viewport_size=720,
)
```

## License

MIT — includes code from [BrowserGym](https://github.com/ServiceNow/BrowserGym) (Apache 2.0).
