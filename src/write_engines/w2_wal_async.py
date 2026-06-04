"""
W2: WAL + Async Batch (Write-Ahead Log style, Kafka/PostgreSQL-inspired)

Every trace is appended to a local WAL (Redis list). A background batch
committer periodically drains the WAL and writes to Cassandra in bulk.
Provides durability guarantees while amortizing global write cost.

Key parameters:
  - BATCH_SIZE: max entries per batch flush
  - BATCH_INTERVAL_MS: max wait before forced flush
"""
import time
import threading
import json
from dataclasses import dataclass

import redis

from src.agent_simulator import AgentSession, TraceEntry

BATCH_SIZE = 10
BATCH_INTERVAL_MS = 500


@dataclass
class W2WriteResult:
    session_id: str
    total_traces: int
    wal_writes: int
    batch_flushes: int
    write_latency_ms: float
    flush_latency_ms: float
    total_bytes_written: int
    avg_batch_size: float


class WALAsyncWriter:
    def __init__(
        self,
        local_redis: redis.Redis,
        cassandra_session,
        batch_size: int = BATCH_SIZE,
        batch_interval_ms: int = BATCH_INTERVAL_MS,
    ):
        self.local = local_redis
        self.cassandra = cassandra_session
        self.batch_size = batch_size
        self.batch_interval_ms = batch_interval_ms
        self._lock = threading.Lock()

    def _wal_key(self, session_id: str) -> str:
        return f"wal:{session_id}"

    def _append_wal(self, trace: TraceEntry) -> float:
        """Append to WAL (Redis list). Returns latency in ms."""
        t0 = time.perf_counter()
        key = self._wal_key(trace.session_id)
        self.local.rpush(key, trace.to_json())
        self.local.expire(key, 3600)
        return (time.perf_counter() - t0) * 1000

    def _drain_wal(self, session_id: str, count: int) -> tuple[list[TraceEntry], float]:
        """Pop `count` entries from WAL and return them with latency."""
        t0 = time.perf_counter()
        key = self._wal_key(session_id)
        raw_entries = []
        pipe = self.local.pipeline()
        for _ in range(count):
            pipe.lpop(key)
        results = pipe.execute()
        for r in results:
            if r is not None:
                raw_entries.append(TraceEntry.from_dict(json.loads(r)))
        latency = (time.perf_counter() - t0) * 1000
        return raw_entries, latency

    def _batch_insert_cassandra(self, traces: list[TraceEntry]) -> float:
        t0 = time.perf_counter()
        for trace in traces:
            self.cassandra.execute(
                """
                INSERT INTO llm_traces.agent_traces
                (trace_id, session_id, turn_index, role, content,
                 timestamp_ms, is_milestone, bytes_size)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    trace.trace_id, trace.session_id, trace.turn_index,
                    trace.role, trace.content, trace.timestamp_ms,
                    trace.is_milestone, trace.bytes_size,
                ),
            )
        return (time.perf_counter() - t0) * 1000

    def write_session(self, session: AgentSession) -> W2WriteResult:
        wal_latencies: list[float] = []
        flush_latencies: list[float] = []
        batch_sizes: list[int] = []
        batch_flushes = 0

        for trace in session.traces:
            lat = self._append_wal(trace)
            wal_latencies.append(lat)

        # Drain WAL in batches (simulating async committer)
        session_id = session.session_id
        remaining = len(session.traces)
        while remaining > 0:
            count = min(self.batch_size, remaining)
            entries, drain_lat = self._drain_wal(session_id, count)
            if not entries:
                break
            flush_lat = self._batch_insert_cassandra(entries)
            flush_latencies.append(drain_lat + flush_lat)
            batch_sizes.append(len(entries))
            batch_flushes += 1
            remaining -= len(entries)

        return W2WriteResult(
            session_id=session.session_id,
            total_traces=len(session.traces),
            wal_writes=len(wal_latencies),
            batch_flushes=batch_flushes,
            write_latency_ms=sum(wal_latencies) / max(len(wal_latencies), 1),
            flush_latency_ms=sum(flush_latencies) / max(len(flush_latencies), 1),
            total_bytes_written=session.total_bytes,
            avg_batch_size=sum(batch_sizes) / max(len(batch_sizes), 1),
        )
