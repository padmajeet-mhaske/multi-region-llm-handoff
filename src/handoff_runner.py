"""
Handoff Runner — orchestrates Region A → B handoffs across all experimental conditions.

Conditions:
  C0: Baseline (W0: naive full write, R0: full context dump)
  C1: Write-Only optimization (W1-W4 vs W0, R0 fixed)
  C2: Read-Only optimization  (W0 fixed, R1-R4 vs R0)
  C3: Hybrid (best write + best read combined)
"""
import time
import json
import logging
from dataclasses import asdict
from typing import Optional

import os
import redis

if os.environ.get("CASSANDRA_STUB", "").strip() != "1":
    from cassandra.cluster import Cluster
    from cassandra.policies import DCAwareRoundRobinPolicy

from src.agent_simulator import AgentSimulator, AgentSession
from src.metrics_collector import MetricsCollector, IterationMetrics

# Write engines
from src.write_engines.w1_selective_flush import SelectiveFlushWriter
from src.write_engines.w2_wal_async import WALAsyncWriter
from src.write_engines.w3_crdt_merge import CRDTMergeWriter
from src.write_engines.w4_adaptive_preflush import AdaptivePreflushWriter

# Read engines
from src.read_engines.r1_hydration_protocol import HydrationProtocolReader
from src.read_engines.r2_llm_summarization import LLMSummarizationReader
from src.read_engines.r3_semantic_rag import SemanticRAGReader
from src.read_engines.r4_memgpt_hierarchical import MemGPTHierarchicalReader

logger = logging.getLogger(__name__)


CASSANDRA_KEYSPACE_DDL = """
CREATE KEYSPACE IF NOT EXISTS llm_traces
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};
"""

CASSANDRA_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS llm_traces.agent_traces (
    trace_id    text PRIMARY KEY,
    session_id  text,
    turn_index  int,
    role        text,
    content     text,
    timestamp_ms double,
    is_milestone boolean,
    bytes_size  int
);
"""

CASSANDRA_CRDT_DDL = """
CREATE TABLE IF NOT EXISTS llm_traces.crdt_states (
    session_id  text,
    region_id   text,
    state_json  text,
    updated_at  timestamp,
    PRIMARY KEY (session_id, region_id)
);
"""


class BaselineWriter:
    """W0: Naive full write — every trace synchronously written to Cassandra."""
    def __init__(self, local_redis: redis.Redis, cassandra_session):
        self.local = local_redis
        self.cassandra = cassandra_session

    def write_session(self, session: AgentSession):
        latencies = []
        for trace in session.traces:
            t0 = time.perf_counter()
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
            latencies.append((time.perf_counter() - t0) * 1000)

        from dataclasses import dataclass
        @dataclass
        class W0Result:
            session_id: str
            write_latency_ms: float
            flush_latency_ms: float
            total_bytes_written: int

        return W0Result(
            session_id=session.session_id,
            write_latency_ms=sum(latencies) / max(len(latencies), 1),
            flush_latency_ms=sum(latencies) / max(len(latencies), 1),
            total_bytes_written=session.total_bytes,
        )


class BaselineReader:
    """R0: Full context dump — sends entire conversation history to Claude."""
    def __init__(self, model: str = "claude-haiku-4-5"):
        self.model = model

    def read_session(self, session: AgentSession):
        from src.claude_client import call_claude, count_tokens
        import json

        messages = session.get_messages()
        messages.append({
            "role": "user",
            "content": "You have been handed off to a new region. Please confirm context and continue.",
        })

        full_bytes = sum(len(json.dumps(m).encode("utf-8")) for m in messages)
        t0 = time.perf_counter()
        result = call_claude(messages=messages, model=self.model, max_tokens=512, use_cache=False)
        latency_ms = (time.perf_counter() - t0) * 1000

        from dataclasses import dataclass
        @dataclass
        class R0Result:
            session_id: str
            algorithm: str
            handoff_latency_ms: float
            context_payload_bytes: int
            context_token_count: int
            compression_ratio: float
            input_token_delta: int
            estimated_cost_usd: float
            state_integrity_score: float

        return R0Result(
            session_id=session.session_id,
            algorithm="R0_FullDump",
            handoff_latency_ms=latency_ms,
            context_payload_bytes=full_bytes,
            context_token_count=result["input_tokens"],
            compression_ratio=1.0,
            input_token_delta=0,
            estimated_cost_usd=result["cost_usd"],
            state_integrity_score=1.0,
        )


def connect_redis(host: str = "localhost", port: int = 6379) -> redis.Redis:
    r = redis.Redis(host=host, port=port, decode_responses=True)
    r.ping()
    return r


def connect_cassandra(host: str = "localhost", port: int = 9042):
    import os
    if os.environ.get("CASSANDRA_STUB", "").strip() == "1":
        from src.cassandra_stub import get_stub_session
        print("  [stub] Using in-memory Cassandra stub (CASSANDRA_STUB=1)")
        return get_stub_session()

    cluster = Cluster(
        [host],
        port=port,
        load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="dc1"),
        protocol_version=4,
    )
    session = cluster.connect()
    session.execute(CASSANDRA_KEYSPACE_DDL)
    session.execute(CASSANDRA_TABLE_DDL)
    session.execute(CASSANDRA_CRDT_DDL)
    return session


class HandoffRunner:
    def __init__(
        self,
        redis_a_host: str = "localhost",
        redis_a_port: int = 6379,
        redis_b_host: str = "localhost",
        redis_b_port: int = 6380,
        cassandra_host: str = "localhost",
        cassandra_port: int = 9042,
        model: str = "claude-haiku-4-5",
    ):
        self.redis_a = connect_redis(redis_a_host, redis_a_port)
        self.redis_b = connect_redis(redis_b_host, redis_b_port)
        self.cassandra = connect_cassandra(cassandra_host, cassandra_port)
        self.model = model
        self.simulator = AgentSimulator(model=model, turns_per_session=6)

        # Initialize all writers
        self.writers = {
            "W0": BaselineWriter(self.redis_a, self.cassandra),
            "W1": SelectiveFlushWriter(self.redis_a, self.cassandra),
            "W2": WALAsyncWriter(self.redis_a, self.cassandra),
            "W3": CRDTMergeWriter(self.redis_a, self.cassandra),
            "W4": AdaptivePreflushWriter(self.redis_a, self.cassandra),
        }

        # Initialize all readers
        self.readers = {
            "R0": BaselineReader(model=model),
            "R1": HydrationProtocolReader(model=model),
            "R2": LLMSummarizationReader(model=model),
            "R3": SemanticRAGReader(model=model),
            "R4": MemGPTHierarchicalReader(model=model),
        }

    def run_single(
        self,
        iteration: int,
        condition: str,
        write_algo: str,
        read_algo: str,
        session: Optional[AgentSession] = None,
    ) -> IterationMetrics:
        if session is None:
            session = self.simulator.generate_session()

        writer = self.writers[write_algo]
        reader = self.readers[read_algo]

        write_result = writer.write_session(session)
        read_result = reader.read_session(session)

        extra = {}
        if hasattr(write_result, "flush_ratio"):
            extra["flush_ratio"] = write_result.flush_ratio
        if hasattr(write_result, "avg_batch_size"):
            extra["avg_batch_size"] = write_result.avg_batch_size
        if hasattr(write_result, "crdt_overhead_bytes"):
            extra["crdt_overhead_bytes"] = write_result.crdt_overhead_bytes
        if hasattr(write_result, "preflush_accuracy"):
            extra["preflush_accuracy"] = write_result.preflush_accuracy
        if hasattr(read_result, "retrieval_latency_ms"):
            extra["retrieval_latency_ms"] = read_result.retrieval_latency_ms
        if hasattr(read_result, "archival_summaries_count"):
            extra["archival_summaries_count"] = read_result.archival_summaries_count

        return IterationMetrics(
            iteration=iteration,
            condition=condition,
            write_algorithm=write_algo,
            read_algorithm=read_algo,
            session_id=session.session_id,
            write_latency_ms=getattr(write_result, "write_latency_ms", 0.0),
            flush_latency_ms=getattr(write_result, "flush_latency_ms", 0.0),
            total_bytes_written=getattr(write_result, "total_bytes_written", 0),
            handoff_latency_ms=getattr(read_result, "handoff_latency_ms", 0.0),
            context_payload_bytes=getattr(read_result, "context_payload_bytes", 0),
            context_token_count=getattr(read_result, "context_token_count", 0),
            compression_ratio=getattr(read_result, "compression_ratio", 1.0),
            input_token_delta=getattr(read_result, "input_token_delta", 0),
            estimated_cost_usd=getattr(read_result, "estimated_cost_usd", 0.0),
            state_integrity_score=getattr(read_result, "state_integrity_score", 1.0),
            extra=json.dumps(extra),
        )

    def run_experiment(
        self,
        pairs: list[tuple[str, str, str]],  # (condition, write_algo, read_algo)
        n_iterations: int = 100,
        collector: Optional[MetricsCollector] = None,
        verbose: bool = True,
    ) -> MetricsCollector:
        if collector is None:
            collector = MetricsCollector()

        total = len(pairs) * n_iterations
        completed = 0

        for condition, write_algo, read_algo in pairs:
            logger.info("Starting %s: %s + %s", condition, write_algo, read_algo)
            for i in range(n_iterations):
                try:
                    metrics = self.run_single(i, condition, write_algo, read_algo)
                    collector.record(metrics)
                    completed += 1
                    if verbose and completed % 10 == 0:
                        pct = completed / total * 100
                        logger.info("Progress: %d/%d (%.1f%%)", completed, total, pct)
                except Exception as exc:
                    logger.error("Iteration %d failed (%s+%s): %s", i, write_algo, read_algo, exc)

        return collector
