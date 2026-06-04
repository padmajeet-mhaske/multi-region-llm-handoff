"""
W3: Concurrent Trace Log G-Set (CRDT Merge)

Based on Shapiro et al. 2011 "A Comprehensive Study of Convergent and
Commutative Replicated Data Types."

Each agent execution step is an immutable event appended to a local G-Set
CRDT paired with a vector clock tracking region causality. On handoff or
network heal, states are resolved via a deterministic join semi-lattice:

    merged = S_A ⊔ S_B
    merged.entries        = S_A.entries ∪ S_B.entries   (union by trace_id)
    merged.vector_clock[r]= max(vc_A[r], vc_B[r])       (component-wise max)

Three real-world scenarios that demand this approach:

  1. Hot Handoff Overlap — Region A finishes a background task (e.g., compiling
     a legal report) while Region B has already taken the active UI session.
     Both regions write traces concurrently for a short overlap window. The
     G-Set union ensures zero traces are lost when handoff completes.

  2. Split-Brain WAN Partition — A network partition forces concurrent execution
     in both regions to maintain availability. On network heal, the CRDT merge
     produces a deterministically ordered, complete trace log with no manual
     conflict resolution.

  3. Multi-Agent Swarm — Sub-agents routed to different regions (e.g., one in
     Tokyo for local API latency, one in Ohio) write to the same session
     concurrently. The G-Set guarantees all sub-agent traces are preserved.

Simulation in this benchmark: We model scenario 1 (hot handoff overlap) by
having Region B independently pre-write the last N_OVERLAP traces of the
session before the merge — producing a non-trivial, measurement-worthy merge.
"""
import time
import json
from dataclasses import dataclass, field

import redis

from src.agent_simulator import AgentSession, TraceEntry

# Number of traces Region B pre-writes independently (simulates overlap window)
N_OVERLAP_TRACES = 2


@dataclass
class CRDTState:
    """
    G-Set CRDT: grow-only set of immutable trace events keyed by trace_id.

    Invariants:
      - entries never shrink (grow-only)
      - merge is idempotent, associative, commutative (join semi-lattice)
      - vector_clock[region] counts local append operations
    """
    region_id: str
    entries: dict[str, dict] = field(default_factory=dict)   # trace_id → trace_dict
    vector_clock: dict[str, int] = field(default_factory=dict)

    def add(self, trace: TraceEntry):
        """Append an immutable trace event. Idempotent by trace_id."""
        self.entries[trace.trace_id] = trace.to_dict()
        self.vector_clock[self.region_id] = (
            self.vector_clock.get(self.region_id, 0) + 1
        )

    def merge(self, other: "CRDTState") -> "CRDTState":
        """
        Join semi-lattice merge: S_self ⊔ S_other.

        Produces a new state whose entries are the union of both G-Sets and
        whose vector clock is the component-wise max. Guarantees strong
        eventual consistency — any two replicas that have received the same
        set of updates will converge to identical state regardless of order.
        """
        merged = CRDTState(region_id=self.region_id)
        # G-Set union — self takes precedence only for identical trace_ids
        # (both regions write identical content for same trace_id, so safe)
        merged.entries = {**other.entries, **self.entries}
        # Component-wise max across all regions seen by either state
        all_regions = set(self.vector_clock) | set(other.vector_clock)
        for region in all_regions:
            merged.vector_clock[region] = max(
                self.vector_clock.get(region, 0),
                other.vector_clock.get(region, 0),
            )
        return merged

    def causally_ordered_traces(self) -> list[dict]:
        """
        Return traces sorted by (turn_index, timestamp_ms) — causal order.

        Vector clocks establish *which region* wrote each trace; turn_index
        establishes the logical order of conversation turns within a session.
        """
        return sorted(
            self.entries.values(),
            key=lambda t: (t.get("turn_index", 0), t.get("timestamp_ms", 0.0)),
        )

    def concurrent_entry_count(self, other: "CRDTState") -> int:
        """Count traces present in both regions (overlap window size)."""
        return len(set(self.entries) & set(other.entries))

    def to_json(self) -> str:
        return json.dumps({
            "region_id": self.region_id,
            "entries": self.entries,
            "vector_clock": self.vector_clock,
        })

    @classmethod
    def from_json(cls, data: str) -> "CRDTState":
        d = json.loads(data)
        state = cls(region_id=d["region_id"])
        state.entries = d["entries"]
        state.vector_clock = d["vector_clock"]
        return state


@dataclass
class W3WriteResult:
    session_id: str
    total_traces: int
    local_writes: int
    concurrent_writes: int          # traces Region B wrote independently (overlap)
    merge_operations: int
    write_latency_ms: float
    flush_latency_ms: float         # alias for merge_latency_ms (runner compatibility)
    merge_latency_ms: float
    total_bytes_written: int
    crdt_overhead_bytes: int        # extra bytes vs raw trace payload for CRDT metadata


class CRDTMergeWriter:
    """
    Write engine that models active-active concurrent execution.

    Region A builds its G-Set as usual. To produce a non-trivial merge,
    we simulate Region B having independently pre-written the last
    N_OVERLAP_TRACES of the session (the hot handoff overlap window).
    The merge of S_A ⊔ S_B then exercises the full CRDT path.
    """

    def __init__(
        self,
        local_redis: redis.Redis,
        cassandra_session,
        region_id: str = "region-a",
        peer_region_id: str = "region-b",
    ):
        self.local = local_redis
        self.cassandra = cassandra_session
        self.region_id = region_id
        self.peer_region_id = peer_region_id

    def _crdt_key(self, session_id: str, region: str) -> str:
        return f"crdt:{session_id}:{region}"

    def _load_state(self, session_id: str, region: str) -> CRDTState:
        raw = self.local.get(self._crdt_key(session_id, region))
        if raw:
            return CRDTState.from_json(raw)
        return CRDTState(region_id=region)

    def _save_state(self, session_id: str, state: CRDTState) -> None:
        self.local.set(
            self._crdt_key(session_id, state.region_id),
            state.to_json(),
            ex=3600,
        )

    def _persist_merged_state(self, state: CRDTState, session_id: str) -> float:
        """Flush final merged CRDT state to Cassandra."""
        t0 = time.perf_counter()
        self.cassandra.execute(
            """
            INSERT INTO llm_traces.crdt_states
            (session_id, region_id, state_json, updated_at)
            VALUES (%s, %s, %s, toTimestamp(now()))
            """,
            (session_id, self.region_id, state.to_json()),
        )
        return (time.perf_counter() - t0) * 1000

    def _build_peer_overlap_state(self, session: AgentSession) -> CRDTState:
        """
        Simulate Region B's concurrent state during the hot handoff overlap.

        Region B independently receives and writes the last N_OVERLAP_TRACES
        traces of the session (e.g., the user's last prompt + the agent's
        last reply arrive at both regions during the handoff window).
        """
        peer = CRDTState(region_id=self.peer_region_id)
        overlap_traces = session.traces[-N_OVERLAP_TRACES:] if len(session.traces) >= N_OVERLAP_TRACES else session.traces
        for trace in overlap_traces:
            peer.add(trace)
        return peer

    def write_session(self, session: AgentSession) -> W3WriteResult:
        write_latencies: list[float] = []
        state = CRDTState(region_id=self.region_id)

        # Region A: append every trace to local G-Set
        for trace in session.traces:
            t0 = time.perf_counter()
            state.add(trace)
            self._save_state(session.session_id, state)
            write_latencies.append((time.perf_counter() - t0) * 1000)

        # Simulate Region B's concurrent overlap state
        peer_state = self._build_peer_overlap_state(session)
        self._save_state(session.session_id, peer_state)
        concurrent_writes = len(peer_state.entries)

        # Join semi-lattice merge: S_A ⊔ S_B
        t_merge = time.perf_counter()
        merged = state.merge(peer_state)
        merge_op_latency = (time.perf_counter() - t_merge) * 1000

        # Flush merged state to Cassandra
        flush_latency = self._persist_merged_state(merged, session.session_id)
        total_merge_latency = merge_op_latency + flush_latency

        crdt_json_bytes = len(merged.to_json().encode("utf-8"))
        raw_bytes = session.total_bytes
        overhead = max(crdt_json_bytes - raw_bytes, 0)

        return W3WriteResult(
            session_id=session.session_id,
            total_traces=len(merged.entries),           # post-merge total (≥ session traces)
            local_writes=len(write_latencies),
            concurrent_writes=concurrent_writes,
            merge_operations=1,
            write_latency_ms=sum(write_latencies) / max(len(write_latencies), 1),
            flush_latency_ms=total_merge_latency,       # runner reads flush_latency_ms
            merge_latency_ms=total_merge_latency,
            total_bytes_written=crdt_json_bytes,
            crdt_overhead_bytes=overhead,
        )
