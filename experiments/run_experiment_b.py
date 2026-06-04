"""
Experiment B: Read Engine Ablation

Compares R0 (full dump baseline) vs R1, R2, R3, R4 with Write engine fixed at W0 (baseline).

Research question: Which read strategy minimizes handoff_latency_ms and
context_token_count while maximizing state_integrity_score?

Usage:
    ANTHROPIC_API_KEY=<your_key> python -m experiments.run_experiment_b \
        --iterations 100 --output results/experiment_b
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.handoff_runner import HandoffRunner
from src.metrics_collector import MetricsCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

READ_ONLY_PAIRS = [
    ("C0_Baseline",      "W0", "R0"),
    ("C2_R1_Hydration",  "W0", "R1"),
    ("C2_R2_Summary",    "W0", "R2"),
    ("C2_R3_RAG",        "W0", "R3"),
    ("C2_R4_MemGPT",     "W0", "R4"),
]


def main():
    parser = argparse.ArgumentParser(description="Experiment B: Read Engine Ablation")
    parser.add_argument("--iterations", type=int, default=100, help="Iterations per condition")
    parser.add_argument("--output", default="results/experiment_b", help="Output directory")
    parser.add_argument("--redis-a-port", type=int, default=6379)
    parser.add_argument("--redis-b-port", type=int, default=6380)
    parser.add_argument("--cassandra-host", default="localhost")
    parser.add_argument("--model", default="claude-haiku-4-5")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== Experiment B: Read Engine Ablation ===")
    logger.info("Conditions: %s", [p[0] for p in READ_ONLY_PAIRS])
    logger.info("Iterations per condition: %d", args.iterations)
    logger.info("Model: %s", args.model)

    runner = HandoffRunner(
        redis_a_port=args.redis_a_port,
        redis_b_port=args.redis_b_port,
        cassandra_host=args.cassandra_host,
        model=args.model,
    )

    collector = MetricsCollector(output_dir=str(output_dir))
    collector = runner.run_experiment(
        pairs=READ_ONLY_PAIRS,
        n_iterations=args.iterations,
        collector=collector,
        verbose=True,
    )

    csv_path = collector.save_csv("experiment_b_raw.csv")
    json_path = collector.save_json("experiment_b_raw.json")
    logger.info("Raw data saved to: %s, %s", csv_path, json_path)

    summary = collector.summary_stats(group_by=["condition", "read_algorithm"])
    summary_path = output_dir / "experiment_b_summary.csv"
    summary.to_csv(summary_path, index=False)
    logger.info("Summary stats saved to: %s", summary_path)

    for metric in ["handoff_latency_ms", "context_token_count", "compression_ratio",
                   "input_token_delta", "estimated_cost_usd"]:
        wtest = collector.wilcoxon_test(
            metric=metric,
            group_col="condition",
            baseline_label="C0_Baseline",
            comparison_labels=["C2_R1_Hydration", "C2_R2_Summary", "C2_R3_RAG", "C2_R4_MemGPT"],
        )
        if not wtest.empty:
            wtest_path = output_dir / f"wilcoxon_{metric}.csv"
            wtest.to_csv(wtest_path, index=False)
            logger.info("Wilcoxon test (%s) saved to: %s", metric, wtest_path)

    logger.info("\n=== Summary ===")
    collector.print_summary()
    logger.info("Experiment B complete.")


if __name__ == "__main__":
    main()
