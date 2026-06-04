"""
R2: LLM Summarization (MemWalker-style)

Before handoff, the current region sends the full conversation to Claude
and asks it to produce a compressed summary. The receiving region uses
the summary as its initial context.

Reference: MemWalker (Chen et al. 2023) — recursive summarization for
long-context navigation.

Trade-off: extra Claude call before handoff (write-side cost) but smaller
context payload for the receiving region.
"""
import time
import json
from dataclasses import dataclass

from src.agent_simulator import AgentSession
from src.claude_client import call_claude, count_tokens, HAIKU_MODEL

SUMMARIZATION_SYSTEM = (
    "You are a context compressor for an AI agent handoff system. "
    "Produce a concise, structured summary that preserves: "
    "(1) the main task and goal, "
    "(2) key decisions and outcomes, "
    "(3) current state and next expected action. "
    "Maximum 200 words."
)

RESUME_SYSTEM = (
    "You are resuming a task. A compressed context summary follows. "
    "Use it to continue naturally without re-explaining the background."
)


@dataclass
class R2ReadResult:
    session_id: str
    algorithm: str
    handoff_latency_ms: float
    summarization_latency_ms: float
    summary_bytes: int
    context_payload_bytes: int
    context_token_count: int
    handoff_output_tokens: int
    input_token_delta: int
    compression_ratio: float
    estimated_cost_usd: float
    state_integrity_score: float
    claude_response: str
    summary_text: str


class LLMSummarizationReader:
    def __init__(self, model: str = HAIKU_MODEL):
        self.model = model

    def _summarize(self, session: AgentSession) -> tuple[str, float, float]:
        """Call Claude to summarize the conversation. Returns (summary, latency_ms, cost)."""
        messages = session.get_messages()
        messages.append({
            "role": "user",
            "content": "Please compress the above conversation into a handoff summary.",
        })

        t0 = time.perf_counter()
        result = call_claude(
            messages=messages,
            system=SUMMARIZATION_SYSTEM,
            model=self.model,
            max_tokens=256,
            use_cache=False,  # summaries vary — no cache benefit
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        return result["content"], latency_ms, result["cost_usd"]

    def _payload_bytes(self, messages: list[dict]) -> int:
        return sum(len(json.dumps(m).encode("utf-8")) for m in messages)

    def _full_payload_bytes(self, session: AgentSession) -> int:
        msgs = session.get_messages()
        msgs.append({"role": "user", "content": "Continue."})
        return self._payload_bytes(msgs)

    def _integrity_score(self, summary: str, session: AgentSession) -> float:
        """Check what fraction of milestone content keywords appear in summary."""
        milestones = session.get_milestone_traces()
        if not milestones:
            return 1.0
        summary_lower = summary.lower()
        # Extract first 30 chars of each milestone as a key phrase
        hit = sum(
            1 for t in milestones
            if any(word in summary_lower for word in t.content.lower().split()[:5])
        )
        return hit / len(milestones)

    def read_session(self, session: AgentSession) -> R2ReadResult:
        # Step 1: Summarize (this happens at the "sending" region)
        summary, summarization_latency_ms, summary_cost = self._summarize(session)

        # Step 2: Resume from summary at receiving region
        resume_messages = [
            {"role": "user", "content": f"Context summary:\n\n{summary}\n\nPlease continue the task."}
        ]

        summary_bytes = len(summary.encode("utf-8"))
        full_bytes = self._full_payload_bytes(session)

        resume_tokens = count_tokens(resume_messages, system=RESUME_SYSTEM, model=self.model)
        full_messages = session.get_messages()
        full_tokens = count_tokens(full_messages, system=RESUME_SYSTEM, model=self.model)

        t0 = time.perf_counter()
        result = call_claude(
            messages=resume_messages,
            system=RESUME_SYSTEM,
            model=self.model,
            max_tokens=512,
            use_cache=True,
        )
        handoff_latency_ms = (time.perf_counter() - t0) * 1000

        total_cost = summary_cost + result["cost_usd"]
        compression_ratio = full_bytes / max(summary_bytes, 1)
        token_delta = full_tokens - resume_tokens
        integrity = self._integrity_score(summary, session)
        payload_bytes = self._payload_bytes(resume_messages)

        return R2ReadResult(
            session_id=session.session_id,
            algorithm="R2_LLMSummarization",
            handoff_latency_ms=handoff_latency_ms,
            summarization_latency_ms=summarization_latency_ms,
            summary_bytes=summary_bytes,
            context_payload_bytes=payload_bytes,
            context_token_count=result["input_tokens"],
            handoff_output_tokens=result["output_tokens"],
            input_token_delta=token_delta,
            compression_ratio=compression_ratio,
            estimated_cost_usd=total_cost,
            state_integrity_score=integrity,
            claude_response=result["content"],
            summary_text=summary,
        )
