"""
W4: Adaptive Pre-flush Algorithm

Predicts handoff likelihood based on:
  - Session age (older sessions more likely to hand off soon)
  - Conversation depth (more turns → more likely near handoff)
  - Time of day / activity pattern heuristics

When predicted handoff probability exceeds PREFLUSH_THRESHOLD, proactively
flushes to global DB to reduce observed handoff latency. The "bet" is that
pre-flushing now is cheaper than flushing urgently at handoff time.
"""
import time
import math
import json
from dataclasses import dataclass

import redis

from src.agent_simulator import AgentSession, TraceEntry

PREFLUSH_THRESHOLD = 0.6     # flush when predicted handoff prob > 60%
MAX_SESSION_TURNS = 20       # expected maximum turns before handoff
SESSION_AGE_WEIGHT = 0.4
DEPTH_WEIGHT = 0.6


@dataclass
class W4WriteResult:
    session_id: str
    total_traces: int
    preflush_triggers: int
    reactive_flushes: int
    write_latency_ms: float
    flush_latency_ms: float
    total_bytes_written: int
    preflush_accuracy: float   # fraction of preflushed that were actually near handoff


class AdaptivePreflushWriter:
    def __init__(
        self,
        local_redis: redis.Redis,
        cassandra_session,
        preflush_threshold: float = PREFLUSH_THRESHOLD,
    ):
        self.local = local_redis
        self.cassandra = cassandra_session
        self.threshold = preflush_threshold

    def _predict_handoff_probability(
        self, turn_index: int, session_start_ms: float, total_turns_so_far: int
    ) -> float:
        """Heuristic handoff probability: sigmoid over session depth + age."""
        now_ms = time.time() * 1000
        age_seconds = (now_ms - session_start_ms) / 1000
        # Depth score: what fraction of expected max turns have elapsed
        depth_score = min(total_turns_so_far / MAX_SESSION_TURNS, 1.0)
        # Age score: sigmoid, peaks after ~30s (simulated fast handoff)
        age_score = 1 / (1 + math.exp(-0.1 * (age_seconds - 10)))
        probability = SESSION_AGE_WEIGHT * age_score + DEPTH_WEIGHT * depth_score
        return min(probability, 1.0)

    def _write_local(self, trace: TraceEntry) -> float:
        t0 = time.perf_counter()
        key = f"trace:{trace.session_id}:{trace.turn_index}"
        self.local.set(key, trace.to_json(), ex=3600)
        return (time.perf_counter() - t0) * 1000

    def _flush_to_global(self, traces: list[TraceEntry]) -> float:
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

    def write_session(self, session: AgentSession) -> W4WriteResult:
        write_latencies: list[float] = []
        flush_latencies: list[float] = []
        unflushed: list[TraceEntry] = []
        preflush_triggers = 0
        reactive_flushes = 0

        session_start_ms = session.traces[0].timestamp_ms if session.traces else time.time() * 1000

        for i, trace in enumerate(session.traces):
            lat = self._write_local(trace)
            write_latencies.append(lat)
            unflushed.append(trace)

            prob = self._predict_handoff_probability(i, session_start_ms, i + 1)
            if prob >= self.threshold and unflushed:
                flush_lat = self._flush_to_global(unflushed)
                flush_latencies.append(flush_lat)
                preflush_triggers += 1
                unflushed = []

        # Reactive flush for any remaining traces
        if unflushed:
            flush_lat = self._flush_to_global(unflushed)
            flush_latencies.append(flush_lat)
            reactive_flushes += 1

        # Accuracy: in a real system, compare preflushes to actual handoffs
        # Here we approximate: if we pre-flushed and had few reactive flushes → good accuracy
        total_flushes = preflush_triggers + reactive_flushes
        accuracy = preflush_triggers / max(total_flushes, 1)

        return W4WriteResult(
            session_id=session.session_id,
            total_traces=len(session.traces),
            preflush_triggers=preflush_triggers,
            reactive_flushes=reactive_flushes,
            write_latency_ms=sum(write_latencies) / max(len(write_latencies), 1),
            flush_latency_ms=sum(flush_latencies) / max(len(flush_latencies), 1),
            total_bytes_written=session.total_bytes,
            preflush_accuracy=accuracy,
        )
