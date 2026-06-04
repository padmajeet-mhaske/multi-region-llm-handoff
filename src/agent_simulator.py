"""
LLM Agent Simulator — generates realistic conversation traces via Claude.

Each "agent session" represents a multi-turn conversation that needs to be
handed off between regions. The simulator produces trace entries that
write engines persist and read engines later hydrate.
"""
import time
import uuid
import json
import random
from dataclasses import dataclass, field, asdict
from typing import Optional

from src.claude_client import call_claude, HAIKU_MODEL

AGENT_SYSTEM_PROMPT = (
    "You are a helpful AI assistant processing a complex multi-step task. "
    "Respond naturally and concisely, as if you are mid-conversation."
)

TASK_SCENARIOS = [
    "Analyze quarterly financial data and identify cost-reduction opportunities.",
    "Debug a distributed microservices outage affecting payment processing.",
    "Generate a product roadmap for the next two quarters.",
    "Draft a technical specification for a new API endpoint.",
    "Evaluate three competing cloud infrastructure proposals.",
    "Summarize recent research papers on transformer architecture improvements.",
    "Plan a phased database migration with zero-downtime requirements.",
    "Review and fix security vulnerabilities in a Python web application.",
]


@dataclass
class TraceEntry:
    trace_id: str
    session_id: str
    turn_index: int
    role: str          # "user" | "assistant"
    content: str
    timestamp_ms: float
    is_milestone: bool = False
    bytes_size: int = field(init=False)

    def __post_init__(self):
        self.bytes_size = len(self.content.encode("utf-8"))

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, d: dict) -> "TraceEntry":
        entry = cls(
            trace_id=d["trace_id"],
            session_id=d["session_id"],
            turn_index=d["turn_index"],
            role=d["role"],
            content=d["content"],
            timestamp_ms=d["timestamp_ms"],
            is_milestone=d.get("is_milestone", False),
        )
        return entry


@dataclass
class AgentSession:
    session_id: str
    scenario: str
    traces: list[TraceEntry] = field(default_factory=list)
    total_bytes: int = 0

    def add_trace(self, entry: TraceEntry):
        self.traces.append(entry)
        self.total_bytes += entry.bytes_size

    def get_messages(self) -> list[dict]:
        return [{"role": t.role, "content": t.content} for t in self.traces]

    def get_milestone_traces(self) -> list[TraceEntry]:
        return [t for t in self.traces if t.is_milestone]

    def get_recent_traces(self, n: int = 2) -> list[TraceEntry]:
        assistant_traces = [t for t in self.traces if t.role == "assistant"]
        return assistant_traces[-n:] if len(assistant_traces) >= n else assistant_traces


class AgentSimulator:
    def __init__(self, model: str = HAIKU_MODEL, turns_per_session: int = 6):
        self.model = model
        self.turns_per_session = turns_per_session

    def _milestone_check(self, turn_index: int, content: str) -> bool:
        """Mark every 3rd turn or turns containing decision keywords as milestones."""
        keywords = ["decided", "confirmed", "completed", "approved", "resolved", "done"]
        return (turn_index % 3 == 0) or any(k in content.lower() for k in keywords)

    def generate_session(self, scenario: Optional[str] = None) -> AgentSession:
        """Run a multi-turn Claude conversation and record all traces."""
        if scenario is None:
            scenario = random.choice(TASK_SCENARIOS)

        session_id = str(uuid.uuid4())
        session = AgentSession(session_id=session_id, scenario=scenario)

        conversation: list[dict] = []
        turn_index = 0

        # Initial user message
        user_content = f"I need your help with the following: {scenario}"
        conversation.append({"role": "user", "content": user_content})

        user_trace = TraceEntry(
            trace_id=str(uuid.uuid4()),
            session_id=session_id,
            turn_index=turn_index,
            role="user",
            content=user_content,
            timestamp_ms=time.time() * 1000,
            is_milestone=True,  # first turn is always a milestone
        )
        session.add_trace(user_trace)
        turn_index += 1

        # Multi-turn loop
        for _ in range(self.turns_per_session - 1):
            result = call_claude(
                messages=conversation,
                system=AGENT_SYSTEM_PROMPT,
                model=self.model,
                max_tokens=256,
                use_cache=True,
            )
            assistant_content = result["content"]
            conversation.append({"role": "assistant", "content": assistant_content})

            assistant_trace = TraceEntry(
                trace_id=str(uuid.uuid4()),
                session_id=session_id,
                turn_index=turn_index,
                role="assistant",
                content=assistant_content,
                timestamp_ms=time.time() * 1000,
                is_milestone=self._milestone_check(turn_index, assistant_content),
            )
            session.add_trace(assistant_trace)
            turn_index += 1

            # Follow-up user message to continue conversation
            if turn_index < self.turns_per_session:
                follow_ups = [
                    "Can you elaborate on that?",
                    "What are the risks involved?",
                    "How long would this take to implement?",
                    "What resources do we need?",
                    "Can you provide a concrete example?",
                ]
                user_follow = random.choice(follow_ups)
                conversation.append({"role": "user", "content": user_follow})

                user_trace = TraceEntry(
                    trace_id=str(uuid.uuid4()),
                    session_id=session_id,
                    turn_index=turn_index,
                    role="user",
                    content=user_follow,
                    timestamp_ms=time.time() * 1000,
                )
                session.add_trace(user_trace)
                turn_index += 1

        return session
