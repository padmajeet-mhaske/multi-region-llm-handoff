"""
W3: CRDT Merge (Conflict-free Replicated Data Type)

Based on Shapiro et al. 2011 "A Comprehensive Study of Convergent and
Commutative Replicated Data Types."

Each region maintains a grow-only set (G-Set) of trace entries. On handoff,
regions perform a CRDT merge: union of both sets. Guarantees eventual
consistency without coordination. Higher write cost due to merge metadata,
but safe under concurrent writes from multiple regions.
"""
import time
import json
from dataclasses import dataclass, field

import redis

from src.agent_simulator import AgentSession, TraceEntry


@dataclass
class CRDTState:
    """G-Set CRDT: entries keyed by trace_id for idempotent merges."""
    region_id: str
    entries: dict[str, dict] = field(default_factory=dict)  # trace_id -> trace_dict
    vector_clock: dict[str, int] = field(default_factory=dict)

    def add(self, trace: TraceEntry):
        self.entries[trace.trace_id] = trace.to_dict()
        self.vector_clock[self.region_id] = self.vector_clock.get(self.region_id, 0) + 1

    def merge(self, other: "CRDTState") -> "CRDTState":
        """Merge two G-Sets — union operation (monotonically grows)."""
        merged = CRDTState(region_id=self.region_id)
        merged.entries = {**other.entries, **self.entries}
        for region, clock in other.vector_clock.items():
            merged.vector_clock[region] = max(
                self.vector_clock.get(region, 0), clock
            )
        for region, clock in self.vector_clock.items():
            merged.vector_clock[region] = max(
                merged.vector_clock.get(region, 0), clock
            )
        return merged

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
    merge_operations: int
    write_latency_ms: float
    merge_latency_ms: float
    total_bytes_written: int
    crdt_overhead_bytes: int       # extra bytes for CRDT metadata


class CRDTMergeWriter:
    def __init__(
        self,
        local_redis: redis.Redis,
        cassandra_session,
        region_id: str = "region-a",
    ):
        self.local = local_redis
        self.cassandra = cassandra_session
        self.region_id = region_id

    def _crdt_key(self, session_id: str) -> str:
        return f"crdt:{session_id}:{self.region_id}"

    def _load_state(self, session_id: str) -> CRDTState:
        raw = self.local.get(self._crdt_key(session_id))
        if raw:
            return CRDTState.from_json(raw)
        return CRDTState(region_id=self.region_id)

    def _save_state(self, session_id: str, state: CRDTState) -> float:
        t0 = time.perf_counter()
        self.local.set(self._crdt_key(session_id), state.to_json(), ex=3600)
        return (time.perf_counter() - t0) * 1000

    def _persist_merged_state(self, state: CRDTState, session_id: str) -> float:
        """Write final merged CRDT state to Cassandra."""
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

    def write_session(self, session: AgentSession) -> W3WriteResult:
        write_latencies: list[float] = []
        merge_latencies: list[float] = []
        state = CRDTState(region_id=self.region_id)

        for trace in session.traces:
            t0 = time.perf_counter()
            state.add(trace)
            lat = self._save_state(session.session_id, state)
            write_latencies.append((time.perf_counter() - t0) * 1000)

        # Simulate merge with a remote region state (empty in baseline, non-trivial in real test)
        t_merge = time.perf_counter()
        remote_state = CRDTState(region_id="region-b")  # empty remote for measurement
        merged = state.merge(remote_state)
        merge_latencies.append((time.perf_counter() - t_merge) * 1000)

        flush_lat = self._persist_merged_state(merged, session.session_id)
        merge_latencies.append(flush_lat)

        crdt_json_bytes = len(merged.to_json().encode("utf-8"))
        raw_bytes = session.total_bytes
        overhead = max(crdt_json_bytes - raw_bytes, 0)

        return W3WriteResult(
            session_id=session.session_id,
            total_traces=len(session.traces),
            local_writes=len(write_latencies),
            merge_operations=1,
            write_latency_ms=sum(write_latencies) / max(len(write_latencies), 1),
            merge_latency_ms=sum(merge_latencies) / max(len(merge_latencies), 1),
            total_bytes_written=crdt_json_bytes,
            crdt_overhead_bytes=overhead,
        )
