"""Claude API wrapper — reads ANTHROPIC_API_KEY from environment only.

Set MOCK_CLAUDE=1 to run without an API key (uses synthetic responses).
Real token counts are approximated from word count in mock mode.
"""
import os
import random
import time
import anthropic

_client: anthropic.Anthropic | None = None

_MOCK_RESPONSES = [
    "I've analyzed the situation and identified three key areas for improvement. First, we should address the latency issues in the service mesh. Second, the database query patterns need optimization. Third, the caching layer requires a configuration update.",
    "Based on the data provided, the root cause appears to be a cascading timeout in the payment processing pipeline. I recommend implementing circuit breakers at each service boundary.",
    "The proposed solution looks viable. Key risks include data migration complexity and potential downtime. I suggest a phased rollout with rollback procedures at each stage.",
    "After reviewing the security vulnerabilities, the most critical issues are SQL injection in the user authentication module and insufficient input validation in the API endpoints.",
    "The quarterly analysis shows a 23% increase in infrastructure costs. Primary drivers are compute over-provisioning and unused reserved instances. Immediate savings of ~$40K/month are achievable.",
    "I've drafted the technical specification. The new API endpoint will support pagination, rate limiting, and JWT authentication. Estimated implementation time is 3 sprints.",
    "Comparing the three cloud proposals: Option A offers best cost at scale, Option B has superior SLA guarantees, Option C provides the fastest migration path. Recommend Option A for long-term value.",
    "The database migration plan is ready. Using a blue-green deployment strategy with read replicas to ensure zero downtime. Estimated migration window: 4 hours on a weekend.",
]


def _mock_call_claude(messages: list[dict], model: str, max_tokens: int) -> dict:
    """Return a synthetic response without calling the API."""
    # Approximate input tokens from total message character count
    total_chars = sum(len(m.get("content", "")) for m in messages)
    input_tokens = max(10, total_chars // 4)

    content = random.choice(_MOCK_RESPONSES)
    output_tokens = len(content.split()) * 4 // 3

    prices = PRICING.get(model, {"input": 1.00, "output": 5.00})
    cost_usd = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000

    return {
        "content": content,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": round(cost_usd, 8),
        "model": model,
    }


def _is_mock() -> bool:
    return os.environ.get("MOCK_CLAUDE", "").strip() == "1"

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
    if _is_mock():
        return _mock_call_claude(messages, model, max_tokens)

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
    if _is_mock():
        total_chars = sum(len(m.get("content", "")) for m in messages) + len(system)
        return max(10, total_chars // 4)

    client = get_client()
    kwargs: dict = {"model": model, "messages": messages}
    if system:
        kwargs["system"] = system
    result = client.messages.count_tokens(**kwargs)
    return result.input_tokens
