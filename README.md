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
--start-url URL     Starting page (default: about:blank)
--api-key KEY       API key (default: EMPTY)
--temperature 0.6   Sampling temperature
--viewport-width N  Browser viewport width (default: 1024)
--viewport-height N Browser viewport height (default: 720)
--headless          Run browser without display
```

### Python API

```python
from bg_chat.agent import run_chat

run_chat(
    base_url="https://your-vllm-endpoint.com/v1",
    model="your-model-name",
    start_url="https://www.google.com",
    viewport_width=1024,
    viewport_height=720,
)
```

## Examples

Run the agent against an A3-Qwen vLLM endpoint and try one of the prompts below.

### Flights — `flights.google.com`

```bash
bg-chat \
  --base-url https://a3-qwen-vllm.mcgill-nlp.org/v1 \
  --start-url https://flights.google.com
```

> show me the 3 cheapest flights from sf to rio for april 22-28 with 2 stops or less

### Hotels — `booking.com`

```bash
bg-chat \
  --base-url https://a3-qwen-vllm.mcgill-nlp.org/v1 \
  --start-url https://www.booking.com
```

> what are the 3 cheapest stays with rating of 8+ in Rio for april 22-28? focus on hotels with breakfast included

### Restaurants — `resy.com`

```bash
bg-chat \
  --base-url https://a3-qwen-vllm.mcgill-nlp.org/v1 \
  --start-url https://resy.com
```

> find 3 highly-rated japanese restaurants in LA with availability for 2 people on April 23

## License

MIT — includes code from [BrowserGym](https://github.com/ServiceNow/BrowserGym) (Apache 2.0).
