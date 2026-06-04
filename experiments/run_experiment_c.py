"""
Experiment C: Hybrid Comparison

Combines best write algorithm from Experiment A with best read algorithm
from Experiment B. Compares all four hybrid combinations against the baseline.

The script accepts --best-write and --best-read args, or defaults to W1 + R1
(the paper's proposed system).

Usage:
    ANTHROPIC_API_KEY=<your_key> python -m experiments.run_experiment_c \
        --iterations 100 --best-write W1 --best-read R1 \
        --output results/experiment_c
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


def build_hybrid_pairs(best_write: str, best_read: str) -> list[tuple[str, str, str]]:
    return [
        ("C0_Baseline",               "W0", "R0"),
        (f"C1_WriteOnly_{best_write}", best_write, "R0"),
        (f"C2_ReadOnly_{best_read}",   "W0",       best_read),
        (f"C3_Hybrid_{best_write}_{best_read}", best_write, best_read),
    ]


def main():
    parser = argparse.ArgumentParser(description="Experiment C: Hybrid Comparison")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--best-write", default="W1",
                        choices=["W1", "W2", "W3", "W4"],
                        help="Best write algorithm from Experiment A")
    parser.add_argument("--best-read", default="R1",
                        choices=["R1", "R2", "R3", "R4"],
                        help="Best read algorithm from Experiment B")
    parser.add_argument("--output", default="results/experiment_c")
    parser.add_argument("--redis-a-port", type=int, default=6379)
    parser.add_argument("--redis-b-port", type=int, default=6380)
    parser.add_argument("--cassandra-host", default="localhost")
    parser.add_argument("--model", default="claude-haiku-4-5")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs = build_hybrid_pairs(args.best_write, args.best_read)

    logger.info("=== Experiment C: Hybrid Comparison ===")
    logger.info("Best write: %s | Best read: %s", args.best_write, args.best_read)
    logger.info("Conditions: %s", [p[0] for p in pairs])
    logger.info("Iterations per condition: %d", args.iterations)

    runner = HandoffRunner(
        redis_a_port=args.redis_a_port,
        redis_b_port=args.redis_b_port,
        cassandra_host=args.cassandra_host,
        model=args.model,
    )

    collector = MetricsCollector(output_dir=str(output_dir))
    collector = runner.run_experiment(
        pairs=pairs,
        n_iterations=args.iterations,
        collector=collector,
        verbose=True,
    )

    csv_path = collector.save_csv("experiment_c_raw.csv")
    json_path = collector.save_json("experiment_c_raw.json")
    logger.info("Raw data saved to: %s, %s", csv_path, json_path)

    summary = collector.summary_stats(group_by=["condition", "write_algorithm", "read_algorithm"])
    summary_path = output_dir / "experiment_c_summary.csv"
    summary.to_csv(summary_path, index=False)
    logger.info("Summary stats saved to: %s", summary_path)

    baseline_label = "C0_Baseline"
    hybrid_label = f"C3_Hybrid_{args.best_write}_{args.best_read}"
    for metric in ["write_latency_ms", "handoff_latency_ms", "context_token_count",
                   "compression_ratio", "estimated_cost_usd"]:
        wtest = collector.wilcoxon_test(
            metric=metric,
            group_col="condition",
            baseline_label=baseline_label,
            comparison_labels=[
                f"C1_WriteOnly_{args.best_write}",
                f"C2_ReadOnly_{args.best_read}",
                hybrid_label,
            ],
        )
        if not wtest.empty:
            wtest_path = output_dir / f"wilcoxon_{metric}.csv"
            wtest.to_csv(wtest_path, index=False)
            logger.info("Wilcoxon test (%s) saved to: %s", metric, wtest_path)

    logger.info("\n=== Summary ===")
    collector.print_summary()

    # Print headline numbers for the paper
    df = collector.to_dataframe()
    for condition in [baseline_label, hybrid_label]:
        subset = df[df["condition"] == condition]
        if subset.empty:
            continue
        logger.info(
            "%s | write_latency p50=%.2fms | handoff p50=%.2fms | cost=$%.6f/iter",
            condition,
            subset["write_latency_ms"].median(),
            subset["handoff_latency_ms"].median(),
            subset["estimated_cost_usd"].mean(),
        )

    logger.info("Experiment C complete.")


if __name__ == "__main__":
    main()
