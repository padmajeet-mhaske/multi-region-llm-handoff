"""
R1: Context Window Hydration Protocol

On region handoff, pulls ONLY:
  - All milestone checkpoints (is_milestone=True)
  - 2 most recent assistant traces

Reduces payload by ~70-80% vs full context dump, saving significant input tokens.
"""
import time
import json
from dataclasses import dataclass

import redis

from src.agent_simulator import AgentSession, TraceEntry
from src.claude_client import call_claude, count_tokens, HAIKU_MODEL

SYSTEM_PROMPT = (
    "You are resuming an ongoing task. Below is a compact context summary "
    "with key checkpoints and the most recent messages. Continue naturally."
)


@dataclass
class R1ReadResult:
    session_id: str
    algorithm: str
    handoff_latency_ms: float
    context_payload_bytes: int
    context_token_count: int
    input_token_delta: int         # tokens saved vs baseline full dump
    compression_ratio: float
    estimated_cost_usd: float
    state_integrity_score: float   # 0-1: how well context was preserved
    claude_response: str


class HydrationProtocolReader:
    def __init__(self, model: str = HAIKU_MODEL):
        self.model = model

    def _build_hydration_payload(self, session: AgentSession) -> list[dict]:
        """Build minimal context: milestones + 2 most recent assistant messages."""
        milestone_traces = session.get_milestone_traces()
        recent_traces = session.get_recent_traces(n=2)

        # Deduplicate by trace_id, preserving turn order
        seen = set()
        selected: list[TraceEntry] = []
        for trace in sorted(milestone_traces + recent_traces, key=lambda t: t.turn_index):
            if trace.trace_id not in seen:
                selected.append(trace)
                seen.add(trace.trace_id)

        messages = [{"role": t.role, "content": t.content} for t in selected]

        # Append handoff trigger
        messages.append({
            "role": "user",
            "content": "You have been handed off to a new region. Please confirm context and continue.",
        })
        return messages

    def _build_full_payload(self, session: AgentSession) -> list[dict]:
        """Baseline: full context dump."""
        messages = session.get_messages()
        messages.append({
            "role": "user",
            "content": "You have been handed off to a new region. Please confirm context and continue.",
        })
        return messages

    def _payload_bytes(self, messages: list[dict]) -> int:
        return sum(len(json.dumps(m).encode("utf-8")) for m in messages)

    def _integrity_score(self, session: AgentSession, hydrated_msgs: list[dict]) -> float:
        """Heuristic: ratio of milestone content that appears in the hydrated context."""
        milestones = session.get_milestone_traces()
        if not milestones:
            return 1.0
        milestone_ids = {t.trace_id for t in milestones}
        included = sum(
            1 for t in session.traces
            if t.trace_id in milestone_ids
            and any(t.content[:50] in m.get("content", "") for m in hydrated_msgs)
        )
        return included / len(milestones)

    def read_session(self, session: AgentSession) -> R1ReadResult:
        t0 = time.perf_counter()

        hydration_msgs = self._build_hydration_payload(session)
        full_msgs = self._build_full_payload(session)

        payload_bytes = self._payload_bytes(hydration_msgs)
        full_bytes = self._payload_bytes(full_msgs)

        hydration_tokens = count_tokens(hydration_msgs, system=SYSTEM_PROMPT, model=self.model)
        full_tokens = count_tokens(full_msgs, system=SYSTEM_PROMPT, model=self.model)

        result = call_claude(
            messages=hydration_msgs,
            system=SYSTEM_PROMPT,
            model=self.model,
            max_tokens=512,
            use_cache=True,
        )

        handoff_latency_ms = (time.perf_counter() - t0) * 1000
        compression_ratio = full_bytes / max(payload_bytes, 1)
        token_delta = full_tokens - hydration_tokens
        integrity = self._integrity_score(session, hydration_msgs)

        return R1ReadResult(
            session_id=session.session_id,
            algorithm="R1_HydrationProtocol",
            handoff_latency_ms=handoff_latency_ms,
            context_payload_bytes=payload_bytes,
            context_token_count=result["input_tokens"],
            input_token_delta=token_delta,
            compression_ratio=compression_ratio,
            estimated_cost_usd=result["cost_usd"],
            state_integrity_score=integrity,
            claude_response=result["content"],
        )
