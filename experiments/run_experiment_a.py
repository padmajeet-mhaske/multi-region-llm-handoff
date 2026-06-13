"""
Experiment A: Write Engine Ablation

Compares W0 (baseline) vs W1, W2, W3, W4 with the Read engine fixed at R0 (full dump).

Research question: Which write strategy minimizes write_latency_ms and
flush_latency_ms while maintaining state_integrity_score?

Usage:
    # Linux / macOS
    ANTHROPIC_API_KEY=<your_key> python -m experiments.run_experiment_a \
        --iterations 100 --output results/experiment_a

    # Windows PowerShell
    $env:ANTHROPIC_API_KEY="<your_key>"
    python -m experiments.run_experiment_a --iterations 100 --output results/experiment_a

    # Windows Command Prompt
    set ANTHROPIC_API_KEY=<your_key>
    python -m experiments.run_experiment_a --iterations 100 --output results/experiment_a
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

WRITE_ONLY_PAIRS = [
    ("C0_Baseline",    "W0", "R0"),
    ("C1_W1_Selective", "W1", "R0"),
    ("C1_W2_WAL",       "W2", "R0"),
    ("C1_W3_CRDT",      "W3", "R0"),
    ("C1_W4_Adaptive",  "W4", "R0"),
]


def main():
    parser = argparse.ArgumentParser(description="Experiment A: Write Engine Ablation")
    parser.add_argument("--iterations", type=int, default=100, help="Iterations per condition")
    parser.add_argument("--output", default="results/experiment_a", help="Output directory")
    parser.add_argument("--redis-a-port", type=int, default=6379)
    parser.add_argument("--redis-b-port", type=int, default=6380)
    parser.add_argument("--cassandra-host", default="localhost")
    parser.add_argument("--model", default="claude-haiku-4-5")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== Experiment A: Write Engine Ablation ===")
    logger.info("Conditions: %s", [p[0] for p in WRITE_ONLY_PAIRS])
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
        pairs=WRITE_ONLY_PAIRS,
        n_iterations=args.iterations,
        collector=collector,
        verbose=True,
    )

    csv_path = collector.save_csv("experiment_a_raw.csv")
    json_path = collector.save_json("experiment_a_raw.json")
    logger.info("Raw data saved to: %s, %s", csv_path, json_path)

    summary = collector.summary_stats(group_by=["condition", "write_algorithm"])
    summary_path = output_dir / "experiment_a_summary.csv"
    summary.to_csv(summary_path, index=False)
    logger.info("Summary stats saved to: %s", summary_path)

    # Wilcoxon tests: write_latency vs baseline
    for metric in ["write_latency_ms", "flush_latency_ms"]:
        wtest = collector.wilcoxon_test(
            metric=metric,
            group_col="condition",
            baseline_label="C0_Baseline",
            comparison_labels=["C1_W1_Selective", "C1_W2_WAL", "C1_W3_CRDT", "C1_W4_Adaptive"],
        )
        if not wtest.empty:
            wtest_path = output_dir / f"wilcoxon_{metric}.csv"
            wtest.to_csv(wtest_path, index=False)
            logger.info("Wilcoxon test (%s) saved to: %s", metric, wtest_path)

    logger.info("\n=== Summary ===")
    collector.print_summary()
    logger.info("Experiment A complete.")


if __name__ == "__main__":
    main()
