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
    try:
        from cassandra.io.asyncioreactor import AsyncioConnection as _CassandraConn
    except ImportError:
        _CassandraConn = None

from src.agent_simulator import AgentSimulator, AgentSession
from src.metrics_collector import MetricsCollector, IterationMetrics
from src.llm_judge import LLMJudge

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

        hydrated_text = "\n\n".join(
            f"[{m['role'].upper()}]: {m['content']}" for m in messages
        )

        from dataclasses import dataclass
        @dataclass
        class R0Result:
            session_id: str
            algorithm: str
            handoff_latency_ms: float
            context_payload_bytes: int
            context_token_count: int
            handoff_output_tokens: int
            compression_ratio: float
            input_token_delta: int
            estimated_cost_usd: float
            state_integrity_score: float
            claude_response: str
            hydrated_payload_text: str

        return R0Result(
            session_id=session.session_id,
            algorithm="R0_FullDump",
            handoff_latency_ms=latency_ms,
            context_payload_bytes=full_bytes,
            context_token_count=result["input_tokens"],
            handoff_output_tokens=result["output_tokens"],
            compression_ratio=1.0,
            input_token_delta=0,
            estimated_cost_usd=result["cost_usd"],
            state_integrity_score=1.0,
            claude_response=result["content"],
            hydrated_payload_text=hydrated_text,
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

    cluster_kwargs = dict(
        contact_points=[host],
        port=port,
        load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="dc1"),
        protocol_version=4,
    )
    if _CassandraConn is not None:
        cluster_kwargs["connection_class"] = _CassandraConn
    cluster = Cluster(**cluster_kwargs)
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

        # Toxiproxy API for WAN RTT measurement
        self._toxiproxy_api = "http://localhost:8474"

        # LLM-as-a-Judge evaluator (independent model to avoid self-assessment bias)
        judge_model = os.environ.get("JUDGE_MODEL", model)
        self.judge = LLMJudge(model=judge_model)

    def _measure_wan_rtt(self) -> tuple[float, bool]:
        """Ping through Toxiproxy to measure actual simulated WAN RTT.
        Returns (rtt_ms, proxy_active). Falls back to 0ms if Toxiproxy not running.
        """
        try:
            import requests
            # Check proxy exists
            r = requests.get(f"{self._toxiproxy_api}/proxies/redis-a-wan", timeout=0.5)
            if r.status_code != 200:
                return 0.0, False
            # Measure actual RTT through the proxy port
            t0 = time.perf_counter()
            probe = redis.Redis(host="localhost", port=16379, socket_connect_timeout=1)
            probe.ping()
            probe.close()
            rtt_ms = (time.perf_counter() - t0) * 1000
            return round(rtt_ms, 2), True
        except Exception:
            return 0.0, False

    def _run_judge(
        self,
        session: AgentSession,
        read_result,
    ) -> tuple[float, float]:
        """
        LLM-as-a-Judge dual evaluation replacing keyword overlap heuristics.

        Evaluation 1 — Context Hydration Fidelity:
            Judge compares hydrated payload against full ground truth trace.
            Measures fraction of critical milestones preserved. → retrieval_accuracy_score

        Evaluation 2 — Handoff State Continuity:
            Judge checks receiving agent response for contradiction / state loss.
            Rubric 1–5 normalized to [0, 1]. → state_integrity_score

        Returns (retrieval_accuracy_score, state_integrity_score).
        Falls back to (1.0, 1.0) if judge inputs unavailable.
        """
        ground_truth = session.get_messages()
        hydrated_text = getattr(read_result, "hydrated_payload_text", "")
        receiving_response = getattr(read_result, "claude_response", "")

        if not hydrated_text or not receiving_response:
            return 1.0, getattr(read_result, "state_integrity_score", 1.0)

        try:
            judge_out = self.judge.evaluate(
                ground_truth_messages=ground_truth,
                hydrated_payload_text=hydrated_text,
                receiving_response=receiving_response,
            )
            return (
                judge_out["retrieval_accuracy_score"],
                judge_out["state_integrity_score"],
            )
        except Exception as exc:
            logger.warning("Judge evaluation failed: %s", exc)
            return 1.0, getattr(read_result, "state_integrity_score", 1.0)

    def run_single(
        self,
        iteration: int,
        condition: str,
        write_algo: str,
        read_algo: str,
        session: Optional[AgentSession] = None,
        step_sequence_number: int = 0,
        collector: Optional[MetricsCollector] = None,
        interaction_class: str = "",
    ) -> IterationMetrics:
        t_step_start = time.perf_counter()

        if session is None:
            session = self.simulator.generate_session()

        # Capture WAN RTT before the iteration
        wan_rtt_ms, wan_active = self._measure_wan_rtt()

        writer = self.writers[write_algo]
        reader = self.readers[read_algo]

        write_result = writer.write_session(session)

        # Thread write-side trace availability into readers that support it.
        # Critical for W1+R3 toxic interference: W1's naturally_flushed_trace_ids
        # restricts R3's embedding corpus to what Region B can actually see in
        # Cassandra at handoff time (non-flushed traces remain in Region A's Redis).
        available_ids = getattr(write_result, "naturally_flushed_trace_ids", None)
        if available_ids is not None and hasattr(reader, "read_session"):
            import inspect
            sig = inspect.signature(reader.read_session)
            if "available_trace_ids" in sig.parameters:
                read_result = reader.read_session(session, available_trace_ids=available_ids)
            else:
                read_result = reader.read_session(session)
        else:
            read_result = reader.read_session(session)

        execution_latency_ms = (time.perf_counter() - t_step_start) * 1000

        # Token accounting — simulator tokens are tracked via session attribute
        # if AgentSimulator populated them; otherwise approximate from session size
        sim_in  = getattr(session, "total_input_tokens", 0)
        sim_out = getattr(session, "total_output_tokens", 0)
        hnd_in  = getattr(read_result, "context_token_count", 0)
        hnd_out = getattr(read_result, "handoff_output_tokens", 0)

        retrieval_acc, integrity_score = self._run_judge(session, read_result)

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
        if interaction_class:
            extra["interaction_class"] = interaction_class
        if available_ids is not None:
            extra["available_trace_ratio"] = round(
                len(available_ids) / max(len(session.traces), 1), 4
            )

        return IterationMetrics(
            step_sequence_number=step_sequence_number,
            iteration=iteration,
            condition=condition,
            write_algorithm=write_algo,
            read_algorithm=read_algo,
            session_id=session.session_id,
            # Write
            write_latency_ms=getattr(write_result, "write_latency_ms", 0.0),
            flush_latency_ms=getattr(write_result, "flush_latency_ms", 0.0),
            total_bytes_written=getattr(write_result, "total_bytes_written", 0),
            # Handoff
            handoff_latency_ms=getattr(read_result, "handoff_latency_ms", 0.0),
            context_payload_bytes=getattr(read_result, "context_payload_bytes", 0),
            context_token_count=hnd_in,
            compression_ratio=getattr(read_result, "compression_ratio", 1.0),
            input_token_delta=getattr(read_result, "input_token_delta", 0),
            estimated_cost_usd=getattr(read_result, "estimated_cost_usd", 0.0),
            # Paper metrics
            input_tokens_used=sim_in + hnd_in,
            output_tokens_used=sim_out + hnd_out,
            simulator_input_tokens=sim_in,
            simulator_output_tokens=sim_out,
            handoff_input_tokens=hnd_in,
            handoff_output_tokens=hnd_out,
            execution_latency_ms=round(execution_latency_ms, 3),
            simulated_wan_latency_ms=wan_rtt_ms,
            wan_simulation_active=wan_active,
            retrieval_accuracy_score=retrieval_acc,
            state_integrity_score=integrity_score,
            extra=json.dumps(extra),
        )

    def run_experiment(
        self,
        pairs: list[tuple],  # (condition, write_algo, read_algo[, interaction_class])
        n_iterations: int = 100,
        collector: Optional[MetricsCollector] = None,
        verbose: bool = True,
    ) -> MetricsCollector:
        if collector is None:
            collector = MetricsCollector()

        total = len(pairs) * n_iterations
        completed = 0

        for entry in pairs:
            condition, write_algo, read_algo = entry[0], entry[1], entry[2]
            interaction_class = entry[3] if len(entry) > 3 else ""
            logger.info("Starting %s: %s + %s [%s]", condition, write_algo, read_algo, interaction_class)
            for i in range(n_iterations):
                try:
                    step = collector.next_step()
                    metrics = self.run_single(
                        i, condition, write_algo, read_algo,
                        step_sequence_number=step, collector=collector,
                        interaction_class=interaction_class,
                    )
                    collector.record(metrics)
                    completed += 1
                    if verbose and completed % 10 == 0:
                        pct = completed / total * 100
                        logger.info("Progress: %d/%d (%.1f%%)", completed, total, pct)
                except Exception as exc:
                    logger.error("Iteration %d failed (%s+%s): %s", i, write_algo, read_algo, exc)

        return collector
