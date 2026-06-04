"""Claude API wrapper — reads ANTHROPIC_API_KEY from environment only."""
import os
import anthropic

_client: anthropic.Anthropic | None = None

HAIKU_MODEL = "claude-haiku-4-5"
SONNET_MODEL = "claude-sonnet-4-6"

# Pricing per million tokens (input / output)
PRICING = {
    HAIKU_MODEL:  {"input": 1.00,  "output": 5.00},
    SONNET_MODEL: {"input": 3.00,  "output": 15.00},
}


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Export it before running experiments."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def call_claude(
    messages: list[dict],
    system: str = "",
    model: str = HAIKU_MODEL,
    max_tokens: int = 1024,
    use_cache: bool = True,
) -> dict:
    """Send a request to Claude and return content + usage stats."""
    client = get_client()

    system_blocks = []
    if system:
        block: dict = {"type": "text", "text": system}
        if use_cache:
            block["cache_control"] = {"type": "ephemeral"}
        system_blocks.append(block)

    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system_blocks:
        kwargs["system"] = system_blocks

    response = client.messages.create(**kwargs)
    usage = response.usage

    prices = PRICING.get(model, {"input": 1.00, "output": 5.00})
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    billed_input = usage.input_tokens - cache_read
    cost_usd = (
        billed_input * prices["input"]
        + usage.output_tokens * prices["output"]
        + cache_read * prices["input"] * 0.1   # cached reads are 10% cost
        + cache_write * prices["input"] * 1.25  # cache write is 25% surcharge
    ) / 1_000_000

    return {
        "content": response.content[0].text if response.content else "",
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "cost_usd": round(cost_usd, 8),
        "model": model,
    }


def count_tokens(messages: list[dict], system: str = "", model: str = HAIKU_MODEL) -> int:
    """Use the token counting endpoint before sending to avoid surprises."""
    client = get_client()
    kwargs: dict = {"model": model, "messages": messages}
    if system:
        kwargs["system"] = system
    result = client.messages.count_tokens(**kwargs)
    return result.input_tokens
