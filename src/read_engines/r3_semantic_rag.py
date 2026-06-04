"""
R3: Semantic RAG Retrieval

On handoff, the receiving region embeds a query ("what is the current task state?")
and retrieves the top-K most semantically relevant traces from the session history
using cosine similarity.

Reference: Lewis et al. 2020 "Retrieval-Augmented Generation for Knowledge-
Intensive NLP Tasks."

Requires sentence-transformers for local embeddings (no API cost for retrieval).
"""
import time
import json
from dataclasses import dataclass

import numpy as np

from src.agent_simulator import AgentSession, TraceEntry
from src.claude_client import call_claude, count_tokens, HAIKU_MODEL

TOP_K = 5
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

RESUME_SYSTEM = (
    "You are resuming a task. The most relevant context fragments have been "
    "retrieved for you. Use them to continue without re-explaining background."
)


@dataclass
class R3ReadResult:
    session_id: str
    algorithm: str
    handoff_latency_ms: float
    retrieval_latency_ms: float
    context_payload_bytes: int
    context_token_count: int
    input_token_delta: int
    compression_ratio: float
    estimated_cost_usd: float
    state_integrity_score: float
    top_k_retrieved: int
    claude_response: str


class SemanticRAGReader:
    def __init__(self, model: str = HAIKU_MODEL, top_k: int = TOP_K):
        self.model = model
        self.top_k = top_k
        self._embedder = None

    def _get_embedder(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(EMBEDDING_MODEL)
        return self._embedder

    def _embed(self, texts: list[str]) -> np.ndarray:
        embedder = self._get_embedder()
        return embedder.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

    def _cosine_similarity(self, query_vec: np.ndarray, corpus_vecs: np.ndarray) -> np.ndarray:
        # Both are already L2-normalized, so dot product = cosine similarity
        return corpus_vecs @ query_vec

    def _retrieve(self, query: str, traces: list[TraceEntry]) -> tuple[list[TraceEntry], float]:
        """Return top-K traces most similar to query. Returns (traces, retrieval_latency_ms)."""
        t0 = time.perf_counter()
        texts = [t.content for t in traces]
        corpus_vecs = self._embed(texts)
        query_vec = self._embed([query])[0]
        scores = self._cosine_similarity(query_vec, corpus_vecs)
        top_indices = np.argsort(scores)[::-1][: self.top_k]
        retrieved = [traces[i] for i in sorted(top_indices)]  # preserve temporal order
        latency = (time.perf_counter() - t0) * 1000
        return retrieved, latency

    def _payload_bytes(self, messages: list[dict]) -> int:
        return sum(len(json.dumps(m).encode("utf-8")) for m in messages)

    def _integrity_score(self, session: AgentSession, retrieved: list[TraceEntry]) -> float:
        milestones = {t.trace_id for t in session.get_milestone_traces()}
        if not milestones:
            return 1.0
        retrieved_ids = {t.trace_id for t in retrieved}
        return len(milestones & retrieved_ids) / len(milestones)

    def read_session(self, session: AgentSession) -> R3ReadResult:
        query = "What is the current task, latest decision, and next action?"
        traces = session.traces

        retrieved, retrieval_latency_ms = self._retrieve(query, traces)

        context_fragments = "\n\n".join(
            f"[Turn {t.turn_index} | {t.role}]: {t.content}" for t in retrieved
        )
        resume_messages = [
            {
                "role": "user",
                "content": (
                    f"Retrieved context fragments:\n\n{context_fragments}\n\n"
                    "Please continue the task from this context."
                ),
            }
        ]

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

        compression_ratio = full_bytes / max(payload_bytes, 1)
        token_delta = full_tokens - resume_tokens
        integrity = self._integrity_score(session, retrieved)

        return R3ReadResult(
            session_id=session.session_id,
            algorithm="R3_SemanticRAG",
            handoff_latency_ms=handoff_latency_ms,
            retrieval_latency_ms=retrieval_latency_ms,
            context_payload_bytes=payload_bytes,
            context_token_count=result["input_tokens"],
            input_token_delta=token_delta,
            compression_ratio=compression_ratio,
            estimated_cost_usd=result["cost_usd"],
            state_integrity_score=integrity,
            top_k_retrieved=len(retrieved),
            claude_response=result["content"],
        )
