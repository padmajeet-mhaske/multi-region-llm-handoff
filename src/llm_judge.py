"""
LLM-as-a-Judge: dual-prompt semantic evaluation for cross-region handoff quality.

Replaces keyword overlap heuristics with two independent Claude evaluations:

  Evaluation 1 — Context Hydration Fidelity (retrieval_accuracy_score)
    Compares the hydrated payload P_hyd against the full ground truth T_gt.
    Measures: fraction of critical milestones preserved after compression.
    Output: JSON float in [0.0, 1.0]

  Evaluation 2 — Handoff State Continuity (state_integrity_score)
    Checks the receiving agent response R_recv for contradiction or state loss
    relative to the ground truth T_gt. Does NOT measure text similarity.
    Rubric 1–5 normalized to [0.0, 1.0]:
      5 → 1.0  Perfect continuity — agent continues seamlessly
      4 → 0.75 Minor redundancy — repeats a minor action, maintains state
      3 → 0.50 State drift — forgets a minor variable or repeats major task
      2 → 0.25 Severe contradiction — acts against a settled past decision
      1 → 0.0  Catastrophic state loss — treats session as entirely new

The judge model should ideally differ from the experiment model to avoid bias.
Default: JUDGE_MODEL env var, else claude-haiku-4-5.

Cost note: each call to evaluate() makes 2 additional API calls per iteration.
Set MOCK_CLAUDE=1 to use heuristic fallback (no API calls, no cost).
"""
import json
import os
import re
import logging

from src.claude_client import call_claude, HAIKU_MODEL

logger = logging.getLogger(__name__)

JUDGE_MODEL = os.environ.get("JUDGE_MODEL", HAIKU_MODEL)

# ---------------------------------------------------------------------------
# System prompts (exactly as specified by reviewer, adapted for JSON output)
# ---------------------------------------------------------------------------

FIDELITY_SYSTEM = """You are a rigorous systems evaluation judge assessing LLM agent context handoff quality.

Your task: compare a Hydrated Payload (compressed context sent to a receiving region) against the Ground Truth Trace (complete uncompressed context).

Identify all critical system milestones in the Ground Truth:
- Decisions made (e.g., "approved", "confirmed", "rejected")
- Variables or states set (e.g., flags, counters, assignments)
- Tools or actions executed
- Key facts established

Count how many of these milestones are preserved in the Hydrated Payload.

Respond with ONLY a valid JSON object in this exact format:
{"score": <float between 0.0 and 1.0>, "milestones_total": <int>, "milestones_preserved": <int>, "reasoning": "<one sentence>"}

Do not include any text outside the JSON object."""

CONTINUITY_SYSTEM = """You are an agentic state alignment judge evaluating whether an AI agent maintains continuity after a cross-region handoff.

Your task: analyze the Ground Truth Trace (the agent's past context) and the Receiving Agent Response (the first output after handoff). Rate State Continuity on this rubric:

5 = Perfect continuity. The agent seamlessly continues the task without asking for repeated information or contradicting past decisions.
4 = Minor redundancy. The agent repeats a minor action but correctly maintains overall state.
3 = State drift. The agent forgets a minor variable or needlessly repeats a major task step.
2 = Severe contradiction. The agent acts in direct opposition to a decision already settled in the past context.
1 = Catastrophic state loss. The agent treats the session as an entirely new interaction with no memory of prior context.

Respond with ONLY a valid JSON object in this exact format:
{"score": <integer 1-5>, "reasoning": "<one sentence explaining the rating>"}

Do not include any text outside the JSON object."""


def _format_trace_text(messages: list[dict]) -> str:
    """Convert a messages list to readable text for the judge."""
    lines = []
    for m in messages:
        role = m.get("role", "unknown").upper()
        content = m.get("content", "")
        lines.append(f"[{role}]: {content}")
    return "\n\n".join(lines)


def _mock_fidelity_score(ground_truth_text: str, hydrated_payload_text: str) -> dict:
    """Heuristic fallback when MOCK_CLAUDE=1 — no API calls."""
    gt_words = set(ground_truth_text.lower().split())
    hyd_words = set(hydrated_payload_text.lower().split())
    overlap = len(gt_words & hyd_words) / max(len(gt_words), 1)
    score = round(min(overlap * 1.5, 1.0), 4)  # scale up slightly vs raw overlap
    return {"score": score, "milestones_total": 3, "milestones_preserved": round(score * 3), "reasoning": "mock heuristic"}


def _mock_continuity_score(ground_truth_text: str, receiving_response: str) -> dict:
    """Heuristic fallback when MOCK_CLAUDE=1 — no API calls."""
    response_lower = receiving_response.lower()
    keywords = ground_truth_text.lower().split()[:20]
    hits = sum(1 for w in keywords if w in response_lower)
    raw = hits / max(len(keywords), 1)
    score = max(1, min(5, round(1 + raw * 4)))
    return {"score": score, "reasoning": "mock heuristic"}


class LLMJudge:
    """
    Dual-prompt LLM-as-a-Judge evaluator for handoff quality.

    Parameters
    ----------
    model : str
        Judge model. Should ideally differ from the experiment model.
    """

    def __init__(self, model: str = JUDGE_MODEL):
        self.model = model
        self._mock = os.environ.get("MOCK_CLAUDE", "").strip() == "1"

    def evaluate_hydration_fidelity(
        self,
        ground_truth_messages: list[dict],
        hydrated_payload_text: str,
    ) -> tuple[float, dict]:
        """
        Evaluation 1: Context Hydration Fidelity.

        Compares the hydrated payload against the full ground truth trace.
        Returns (score_0_to_1, raw_judge_response_dict).

        Parameters
        ----------
        ground_truth_messages : list[dict]
            Full uncompressed session messages (role/content dicts).
        hydrated_payload_text : str
            Text of what was actually sent to the receiving region's LLM.
        """
        ground_truth_text = _format_trace_text(ground_truth_messages)

        if self._mock:
            raw = _mock_fidelity_score(ground_truth_text, hydrated_payload_text)
            return float(raw["score"]), raw

        messages = [
            {
                "role": "user",
                "content": (
                    "## Ground Truth Trace (complete context)\n\n"
                    f"{ground_truth_text}\n\n"
                    "---\n\n"
                    "## Hydrated Payload (compressed context sent to receiving region)\n\n"
                    f"{hydrated_payload_text}\n\n"
                    "Evaluate the fraction of critical milestones preserved."
                ),
            }
        ]

        try:
            result = call_claude(
                messages=messages,
                system=FIDELITY_SYSTEM,
                model=self.model,
                max_tokens=256,
                use_cache=False,
            )
            raw = _parse_json_response(result["content"], {"score": 0.5, "milestones_total": 0, "milestones_preserved": 0, "reasoning": "parse error"})
            score = float(raw.get("score", 0.5))
            score = max(0.0, min(1.0, score))
            return score, raw
        except Exception as e:
            logger.warning("Judge fidelity call failed: %s", e)
            return 0.5, {"score": 0.5, "reasoning": f"error: {e}"}

    def evaluate_state_continuity(
        self,
        ground_truth_messages: list[dict],
        receiving_response: str,
    ) -> tuple[float, dict]:
        """
        Evaluation 2: Handoff State Continuity.

        Checks the receiving agent response for contradiction or state loss
        relative to the ground truth. Uses a 1–5 rubric normalized to [0, 1].
        Returns (normalized_score_0_to_1, raw_judge_response_dict).

        Parameters
        ----------
        ground_truth_messages : list[dict]
            Full uncompressed session messages.
        receiving_response : str
            The first output generated by the receiving agent after handoff.
        """
        ground_truth_text = _format_trace_text(ground_truth_messages)

        if self._mock:
            raw = _mock_continuity_score(ground_truth_text, receiving_response)
            normalized = (int(raw["score"]) - 1) / 4
            return round(normalized, 4), raw

        messages = [
            {
                "role": "user",
                "content": (
                    "## Ground Truth Trace (past context before handoff)\n\n"
                    f"{ground_truth_text}\n\n"
                    "---\n\n"
                    "## Receiving Agent Response (first output after handoff)\n\n"
                    f"{receiving_response}\n\n"
                    "Rate the state continuity on the 1–5 rubric."
                ),
            }
        ]

        try:
            result = call_claude(
                messages=messages,
                system=CONTINUITY_SYSTEM,
                model=self.model,
                max_tokens=128,
                use_cache=False,
            )
            raw = _parse_json_response(result["content"], {"score": 3, "reasoning": "parse error"})
            score_1_5 = int(raw.get("score", 3))
            score_1_5 = max(1, min(5, score_1_5))
            normalized = round((score_1_5 - 1) / 4, 4)
            return normalized, raw
        except Exception as e:
            logger.warning("Judge continuity call failed: %s", e)
            return 0.5, {"score": 3, "reasoning": f"error: {e}"}

    def evaluate(
        self,
        ground_truth_messages: list[dict],
        hydrated_payload_text: str,
        receiving_response: str,
    ) -> dict:
        """
        Run both evaluations and return a combined result dict.

        Returns
        -------
        dict with keys:
            retrieval_accuracy_score  float [0, 1]
            state_integrity_score     float [0, 1]
            fidelity_raw              dict  (judge's full JSON response)
            continuity_raw            dict
        """
        fidelity_score, fidelity_raw = self.evaluate_hydration_fidelity(
            ground_truth_messages, hydrated_payload_text
        )
        continuity_score, continuity_raw = self.evaluate_state_continuity(
            ground_truth_messages, receiving_response
        )
        return {
            "retrieval_accuracy_score": fidelity_score,
            "state_integrity_score": continuity_score,
            "fidelity_raw": fidelity_raw,
            "continuity_raw": continuity_raw,
        }


def _parse_json_response(text: str, fallback: dict) -> dict:
    """Extract JSON from judge response, with fallback on parse failure."""
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting JSON block with regex
    match = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    logger.warning("Could not parse judge JSON from: %s", text[:200])
    return fallback
