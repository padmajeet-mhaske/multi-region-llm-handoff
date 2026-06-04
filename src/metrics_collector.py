"""
Metrics Collector — captures all per-iteration measurements and produces
summary statistics for paper-quality reporting.
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
    iteration: int
    condition: str          # C0/C1/C2/C3
    write_algorithm: str    # W0/W1/W2/W3/W4
    read_algorithm: str     # R0/R1/R2/R3/R4
    session_id: str

    # Write metrics
    write_latency_ms: float = 0.0
    flush_latency_ms: float = 0.0
    total_bytes_written: int = 0

    # Handoff / read metrics
    handoff_latency_ms: float = 0.0
    context_payload_bytes: int = 0
    context_token_count: int = 0
    compression_ratio: float = 1.0
    input_token_delta: int = 0
    estimated_cost_usd: float = 0.0
    state_integrity_score: float = 1.0

    # Extra algorithm-specific fields (stored as JSON string)
    extra: str = "{}"

    def to_dict(self) -> dict:
        return asdict(self)


class MetricsCollector:
    def __init__(self, output_dir: str = "results"):
        self.records: list[IterationMetrics] = []
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

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
        """Compute p50/p95/p99 and mean for key metrics, grouped by algorithm."""
        if group_by is None:
            group_by = ["condition", "write_algorithm", "read_algorithm"]

        df = self.to_dataframe()
        if df.empty:
            return df

        numeric_cols = [
            "write_latency_ms", "flush_latency_ms",
            "handoff_latency_ms", "context_payload_bytes",
            "context_token_count", "compression_ratio",
            "input_token_delta", "estimated_cost_usd",
            "state_integrity_score",
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

    def print_summary(self):
        df = self.summary_stats()
        if df.empty:
            print("No data collected yet.")
            return
        with pd.option_context("display.max_columns", None, "display.width", 120):
            print(df.to_string(index=False))
