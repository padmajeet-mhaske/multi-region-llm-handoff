"""
W1: Selective Flush Algorithm

Agent traces stay in local Redis (<2ms). Flush to global Cassandra triggers on:
  1. Compliance milestones (milestone flag on trace)
  2. Unflushed buffer exceeds FLUSH_THRESHOLD_BYTES (50KB)

Expected: ~65-75% latency reduction vs naive full-write baseline.
"""
import time
import json
from dataclasses import dataclass, field

import redis

from src.agent_simulator import AgentSession, TraceEntry

FLUSH_THRESHOLD_BYTES = 50 * 1024  # 50 KB


@dataclass
class W1WriteResult:
    session_id: str
    total_traces: int
    local_writes: int
    global_flushes: int
    write_latency_ms: float        # avg per-trace local write
    flush_latency_ms: float        # avg per-flush global write
    total_bytes_written: int
    flush_ratio: float             # flushes / total writes


class SelectiveFlushWriter:
    def __init__(
        self,
        local_redis: redis.Redis,
        cassandra_session,
        flush_threshold_bytes: int = FLUSH_THRESHOLD_BYTES,
    ):
        self.local = local_redis
        self.cassandra = cassandra_session
        self.threshold = flush_threshold_bytes

    def _write_local(self, trace: TraceEntry) -> float:
        """Write trace to local Redis. Returns latency in ms."""
        t0 = time.perf_counter()
        key = f"trace:{trace.session_id}:{trace.turn_index}"
        self.local.set(key, trace.to_json(), ex=3600)
        return (time.perf_counter() - t0) * 1000

    def _flush_to_global(self, session_id: str, traces: list[TraceEntry]) -> float:
        """Flush a batch of traces to Cassandra. Returns latency in ms."""
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

    def write_session(self, session: AgentSession) -> W1WriteResult:
        local_latencies: list[float] = []
        flush_latencies: list[float] = []
        unflushed_buffer: list[TraceEntry] = []
        unflushed_bytes = 0
        global_flushes = 0

        for trace in session.traces:
            # Always write to local Redis first
            lat = self._write_local(trace)
            local_latencies.append(lat)
            unflushed_buffer.append(trace)
            unflushed_bytes += trace.bytes_size

            # Selective flush conditions
            should_flush = trace.is_milestone or unflushed_bytes >= self.threshold
            if should_flush and unflushed_buffer:
                flush_lat = self._flush_to_global(session.session_id, unflushed_buffer)
                flush_latencies.append(flush_lat)
                global_flushes += 1
                unflushed_buffer = []
                unflushed_bytes = 0

        # Flush any remaining traces at session end
        if unflushed_buffer:
            flush_lat = self._flush_to_global(session.session_id, unflushed_buffer)
            flush_latencies.append(flush_lat)
            global_flushes += 1

        return W1WriteResult(
            session_id=session.session_id,
            total_traces=len(session.traces),
            local_writes=len(local_latencies),
            global_flushes=global_flushes,
            write_latency_ms=sum(local_latencies) / max(len(local_latencies), 1),
            flush_latency_ms=sum(flush_latencies) / max(len(flush_latencies), 1),
            total_bytes_written=session.total_bytes,
            flush_ratio=global_flushes / max(len(session.traces), 1),
        )
