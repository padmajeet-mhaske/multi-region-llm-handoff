"""
R4: MemGPT-style Hierarchical Memory

Organizes traces into three tiers:
  - Main context: last N turns (fits in context window)
  - Archival storage: older turns compressed into recursive summaries
  - External storage: Cassandra-backed full history

On handoff, retrieves main context + relevant archival summaries.
Inspired by: Packer et al. 2023 "MemGPT: Towards LLMs as Operating Systems."
"""
import time
import json
from dataclasses import dataclass, field

from src.agent_simulator import AgentSession, TraceEntry
from src.claude_client import call_claude, count_tokens, HAIKU_MODEL

MAIN_CONTEXT_TURNS = 4     # most recent turns always included
ARCHIVE_SUMMARY_TURNS = 3  # compress older turns into 1 summary per N turns

RESUME_SYSTEM = (
    "You are resuming a task using a hierarchical memory system. "
    "You have: (1) a recursive archival summary of older context, "
    "(2) your most recent turns. Continue seamlessly."
)

ARCHIVE_COMPRESS_SYSTEM = (
    "Compress these conversation turns into a dense, factual summary "
    "that preserves goals, decisions, and state. Max 100 words."
)


@dataclass
class MemoryTier:
    main_context: list[dict] = field(default_factory=list)
    archival_summaries: list[str] = field(default_factory=list)
    total_archived_turns: int = 0


@dataclass
class R4ReadResult:
    session_id: str
    algorithm: str
    handoff_latency_ms: float
    archival_compression_latency_ms: float
    context_payload_bytes: int
    context_token_count: int
    handoff_output_tokens: int
    input_token_delta: int
    compression_ratio: float
    estimated_cost_usd: float
    state_integrity_score: float
    archival_summaries_count: int
    claude_response: str


class MemGPTHierarchicalReader:
    def __init__(self, model: str = HAIKU_MODEL):
        self.model = model

    def _compress_chunk(self, traces: list[TraceEntry]) -> tuple[str, float]:
        """Compress a chunk of traces into an archival summary."""
        chunk_text = "\n".join(
            f"[{t.role} turn {t.turn_index}]: {t.content}" for t in traces
        )
        messages = [{"role": "user", "content": chunk_text}]
        t0 = time.perf_counter()
        result = call_claude(
            messages=messages,
            system=ARCHIVE_COMPRESS_SYSTEM,
            model=self.model,
            max_tokens=150,
            use_cache=False,
        )
        latency = (time.perf_counter() - t0) * 1000
        return result["content"], latency

    def _build_memory_tiers(
        self, session: AgentSession
    ) -> tuple[MemoryTier, float, float]:
        """Split traces into main context and archival tiers.

        Returns (MemoryTier, compression_latency_ms, compression_cost_usd)
        """
        traces = session.traces
        tier = MemoryTier()
        total_compress_latency = 0.0
        total_compress_cost = 0.0

        if len(traces) <= MAIN_CONTEXT_TURNS:
            tier.main_context = [{"role": t.role, "content": t.content} for t in traces]
            return tier, total_compress_latency, total_compress_cost

        archive_traces = traces[:-MAIN_CONTEXT_TURNS]
        main_traces = traces[-MAIN_CONTEXT_TURNS:]

        tier.main_context = [{"role": t.role, "content": t.content} for t in main_traces]
        tier.total_archived_turns = len(archive_traces)

        # Chunk archive into groups of ARCHIVE_SUMMARY_TURNS
        for i in range(0, len(archive_traces), ARCHIVE_SUMMARY_TURNS):
            chunk = archive_traces[i: i + ARCHIVE_SUMMARY_TURNS]
            summary, latency = self._compress_chunk(chunk)
            tier.archival_summaries.append(summary)
            total_compress_latency += latency

        return tier, total_compress_latency, total_compress_cost

    def _build_resume_messages(self, tier: MemoryTier) -> list[dict]:
        archival_block = ""
        if tier.archival_summaries:
            archival_block = "=== Archival Memory ===\n" + "\n---\n".join(
                f"[Archive {i+1}]: {s}" for i, s in enumerate(tier.archival_summaries)
            )

        context_block = "=== Main Context (recent turns) ===\n" + "\n".join(
            f"[{m['role']}]: {m['content']}" for m in tier.main_context
        )

        combined = f"{archival_block}\n\n{context_block}" if archival_block else context_block
        return [
            {"role": "user", "content": f"{combined}\n\nPlease continue the task from this state."}
        ]

    def _payload_bytes(self, messages: list[dict]) -> int:
        return sum(len(json.dumps(m).encode("utf-8")) for m in messages)

    def _integrity_score(self, session: AgentSession, tier: MemoryTier) -> float:
        milestones = session.get_milestone_traces()
        if not milestones:
            return 1.0
        archival_text = " ".join(tier.archival_summaries).lower()
        main_text = " ".join(m["content"] for m in tier.main_context).lower()
        full_text = archival_text + " " + main_text
        hit = sum(
            1 for t in milestones
            if any(w in full_text for w in t.content.lower().split()[:5])
        )
        return hit / len(milestones)

    def read_session(self, session: AgentSession) -> R4ReadResult:
        tier, compress_latency_ms, compress_cost = self._build_memory_tiers(session)

        resume_messages = self._build_resume_messages(tier)

        full_msgs = session.get_messages()
        full_msgs.append({"role": "user", "content": "Continue."})
        full_bytes = self._payload_bytes(full_msgs)
        full_tokens = count_tokens(full_msgs, system=RESUME_SYSTEM, model=self.model)

        payload_bytes = self._payload_bytes(resume_messages)
        resume_tokens = count_tokens(resume_messages, system=RESUME_SYSTEM, model=self.model)

        t0 = time.perf_counter()
        result = call_claude(
            messages=resume_messages,
            system=RESUME_SYSTEM,
            model=self.model,
            max_tokens=512,
            use_cache=True,
        )
        handoff_latency_ms = (time.perf_counter() - t0) * 1000

        total_cost = compress_cost + result["cost_usd"]
        compression_ratio = full_bytes / max(payload_bytes, 1)
        token_delta = full_tokens - resume_tokens
        integrity = self._integrity_score(session, tier)

        return R4ReadResult(
            session_id=session.session_id,
            algorithm="R4_MemGPTHierarchical",
            handoff_latency_ms=handoff_latency_ms,
            archival_compression_latency_ms=compress_latency_ms,
            context_payload_bytes=payload_bytes,
            context_token_count=result["input_tokens"],
            handoff_output_tokens=result["output_tokens"],
            input_token_delta=token_delta,
            compression_ratio=compression_ratio,
            estimated_cost_usd=total_cost,
            state_integrity_score=integrity,
            archival_summaries_count=len(tier.archival_summaries),
            claude_response=result["content"],
        )
