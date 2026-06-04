"""
Metrics Collector — captures all per-iteration measurements and produces
summary statistics for paper-quality reporting.

Metric mapping to paper figures:
    step_sequence_number   → X-axis for cost scaling plots
    simulated_wan_latency  → X-axis for latency survival / CDF plots
    input_tokens_used      → token efficiency comparisons
    output_tokens_used     → output verbosity tracking
    execution_latency_ms   → total step wall-clock time (write + handoff)
    retrieval_accuracy_score → Y-axis for attention / context fidelity plots
"""
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class IterationMetrics:
    # --- Identity ---
    step_sequence_number: int       # Global step counter across entire experiment run
    iteration: int                  # Per-condition iteration index
    condition: str                  # C0/C1/C2/C3
    write_algorithm: str            # W0/W1/W2/W3/W4
    read_algorithm: str             # R0/R1/R2/R3/R4
    session_id: str

    # --- Write metrics ---
    write_latency_ms: float = 0.0
    flush_latency_ms: float = 0.0
    total_bytes_written: int = 0

    # --- Handoff / read metrics ---
    handoff_latency_ms: float = 0.0
    context_payload_bytes: int = 0
    context_token_count: int = 0    # input tokens for handoff call (from response.usage)
    compression_ratio: float = 1.0
    input_token_delta: int = 0
    estimated_cost_usd: float = 0.0

    # --- Comprehensive token tracking (maps to paper metrics) ---
    input_tokens_used: int = 0      # total input tokens this iteration (simulator + handoff)
    output_tokens_used: int = 0     # total output tokens this iteration (simulator + handoff)
    simulator_input_tokens: int = 0 # input tokens consumed by AgentSimulator turns
    simulator_output_tokens: int = 0
    handoff_input_tokens: int = 0   # input tokens consumed by ReadEngine handoff call
    handoff_output_tokens: int = 0

    # --- Latency (maps to paper metrics) ---
    execution_latency_ms: float = 0.0   # total wall-clock: write + handoff combined

    # --- WAN simulation (maps to paper metrics) ---
    simulated_wan_latency_ms: float = 0.0   # measured Toxiproxy RTT at time of iteration
    wan_simulation_active: bool = False      # True when Toxiproxy proxy is up

    # --- Retrieval / fidelity (maps to paper metrics) ---
    retrieval_accuracy_score: float = 1.0   # fraction of milestone IDs present in hydrated context
    state_integrity_score: float = 1.0      # keyword-overlap heuristic (legacy, kept for back-compat)

    # --- Algorithm-specific extras ---
    extra: str = "{}"

    def to_dict(self) -> dict:
        return asdict(self)


class MetricsCollector:
    def __init__(self, output_dir: str = "results"):
        self.records: list[IterationMetrics] = []
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._global_step = 0

    def next_step(self) -> int:
        """Return and increment the global step counter."""
        step = self._global_step
        self._global_step += 1
        return step

    def record(self, metrics: IterationMetrics):
        self.records.append(metrics)

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([r.to_dict() for r in self.records])

    def save_csv(self, filename: str) -> Path:
        df = self.to_dataframe()
        path = self.output_dir / filename
        df.to_csv(path, index=False)
        return path

    def save_json(self, filename: str) -> Path:
        path = self.output_dir / filename
        with open(path, "w") as f:
            json.dump([r.to_dict() for r in self.records], f, indent=2)
        return path

    def summary_stats(self, group_by: list[str] = None) -> pd.DataFrame:
        """Compute p50/p95/p99 and mean for all numeric metrics, grouped by algorithm."""
        if group_by is None:
            group_by = ["condition", "write_algorithm", "read_algorithm"]

        df = self.to_dataframe()
        if df.empty:
            return df

        numeric_cols = [
            # Write
            "write_latency_ms", "flush_latency_ms", "total_bytes_written",
            # Handoff
            "handoff_latency_ms", "context_payload_bytes",
            "context_token_count", "compression_ratio",
            "input_token_delta", "estimated_cost_usd",
            # Paper metrics
            "input_tokens_used", "output_tokens_used",
            "simulator_input_tokens", "simulator_output_tokens",
            "handoff_input_tokens", "handoff_output_tokens",
            "execution_latency_ms", "simulated_wan_latency_ms",
            "retrieval_accuracy_score", "state_integrity_score",
        ]

        rows = []
        for keys, group in df.groupby(group_by):
            row: dict[str, Any] = dict(zip(group_by, keys if isinstance(keys, tuple) else [keys]))
            row["n"] = len(group)
            for col in numeric_cols:
                if col in group.columns:
                    vals = group[col].dropna().values
                    if len(vals):
                        row[f"{col}_mean"] = float(np.mean(vals))
                        row[f"{col}_p50"] = float(np.percentile(vals, 50))
                        row[f"{col}_p95"] = float(np.percentile(vals, 95))
                        row[f"{col}_p99"] = float(np.percentile(vals, 99))
                        row[f"{col}_std"] = float(np.std(vals))
            rows.append(row)

        return pd.DataFrame(rows)

    def wilcoxon_test(
        self,
        metric: str,
        group_col: str,
        baseline_label: str,
        comparison_labels: list[str],
    ) -> pd.DataFrame:
        """Wilcoxon signed-rank test vs baseline for each comparison group."""
        df = self.to_dataframe()
        baseline_vals = df[df[group_col] == baseline_label][metric].dropna().values
        results = []
        for label in comparison_labels:
            comp_vals = df[df[group_col] == label][metric].dropna().values
            min_len = min(len(baseline_vals), len(comp_vals))
            if min_len < 2:
                continue
            stat, p_value = stats.wilcoxon(
                baseline_vals[:min_len], comp_vals[:min_len], alternative="greater"
            )
            effect_size = (np.median(baseline_vals) - np.median(comp_vals)) / (
                np.std(baseline_vals) + 1e-9
            )
            results.append({
                "metric": metric,
                "baseline": baseline_label,
                "comparison": label,
                "n": min_len,
                "statistic": stat,
                "p_value": p_value,
                "significant_p05": p_value < 0.05,
                "effect_size": effect_size,
                "median_reduction": float(np.median(baseline_vals) - np.median(comp_vals)),
            })
        return pd.DataFrame(results)

    def cost_scaling_series(self) -> pd.DataFrame:
        """
        Returns cumulative cost by step_sequence_number.
        Use as X=step_sequence_number, Y=cumulative_cost_usd for cost scaling plots.
        """
        df = self.to_dataframe().sort_values("step_sequence_number")
        df["cumulative_cost_usd"] = df["estimated_cost_usd"].cumsum()
        df["cumulative_input_tokens"] = df["input_tokens_used"].cumsum()
        df["cumulative_output_tokens"] = df["output_tokens_used"].cumsum()
        return df[["step_sequence_number", "condition", "write_algorithm", "read_algorithm",
                   "estimated_cost_usd", "cumulative_cost_usd",
                   "input_tokens_used", "cumulative_input_tokens",
                   "output_tokens_used", "cumulative_output_tokens"]]

    def latency_survival(self) -> pd.DataFrame:
        """
        Returns data for latency survival / CDF curves.
        Use as X=simulated_wan_latency_ms, Y=execution_latency_ms grouped by algorithm.
        """
        df = self.to_dataframe()
        return df[["condition", "write_algorithm", "read_algorithm",
                   "simulated_wan_latency_ms", "execution_latency_ms",
                   "handoff_latency_ms", "write_latency_ms"]].copy()

    def attention_tracking(self) -> pd.DataFrame:
        """
        Returns retrieval accuracy by step for attention / context fidelity plots.
        Use as X=step_sequence_number, Y=retrieval_accuracy_score.
        """
        df = self.to_dataframe().sort_values("step_sequence_number")
        return df[["step_sequence_number", "condition", "read_algorithm",
                   "retrieval_accuracy_score", "state_integrity_score",
                   "input_tokens_used", "compression_ratio"]].copy()

    def print_summary(self):
        df = self.summary_stats()
        if df.empty:
            print("No data collected yet.")
            return
        key_cols = [c for c in df.columns if any(
            m in c for m in ["condition", "write_algo", "read_algo", "n",
                              "execution_latency", "input_tokens_used",
                              "retrieval_accuracy", "estimated_cost", "wan_latency"]
        )]
        with pd.option_context("display.max_columns", None, "display.width", 140):
            print(df[key_cols].to_string(index=False) if key_cols else df.to_string(index=False))
