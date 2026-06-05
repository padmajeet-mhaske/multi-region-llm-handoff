"""
Experiment D: Full Write × Read Compatibility Surface (5×5 = 25 combinations)

Exhaustively benchmarks every combination of write engine (W0–W4) against every
read engine (R0–R4), producing the complete 25-cell compatibility matrix needed
for the 3D surface plot and heatmap figures in the paper.

Why this matters:
  Experiments A and B isolate each axis independently.
  Experiment C tests 5 hand-picked combinations.
  Experiment D fills in all 25 cells — revealing unexpected synergies and toxic
  interference patterns that targeted sampling misses entirely.

Output:
  - experiment_d_raw.csv / .json         — per-iteration records
  - experiment_d_summary.csv             — per-(W,R) pair statistics
  - experiment_d_heatmap_<metric>.png    — 2D heatmap figures (5×5)
  - experiment_d_surface_<metric>.png    — 3D surface figures (optional)
  - wilcoxon_<metric>.csv               — significance vs W0+R0 baseline

Cost estimate (claude-haiku-4-5):
  ~$0.003 per iteration (average across all pairs; R2 pairs cost more ~$0.005)
  10  iterations/pair →  25 ×  10 × $0.003 =   $0.75   (quick validation)
  100 iterations/pair →  25 × 100 × $0.003 =   $7.50   (paper-quality)
  1000 iterations/pair → 25 × 1000 × $0.003 = $75.00   (final paper submission)

⚠ DISABLED BY DEFAULT — pass --enabled to run.

Usage:
    ANTHROPIC_API_KEY=<key> python -m experiments.run_experiment_d \\
        --enabled \\
        --iterations 100 \\
        --output results/experiment_d
"""
import argparse
import logging
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.handoff_runner import HandoffRunner
from src.metrics_collector import MetricsCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Full 5×5 matrix definition
# ---------------------------------------------------------------------------

WRITE_ALGOS = ["W0", "W1", "W2", "W3", "W4"]
READ_ALGOS  = ["R0", "R1", "R2", "R3", "R4"]

# Known interaction classes for labelled cells (from Experiment C analysis)
KNOWN_CLASSES = {
    ("W0", "R0"): "Baseline",
    ("W2", "R1"): "HighlySynergistic",
    ("W1", "R3"): "CatastrophicInterference",
    ("W4", "R2"): "HighRiskHighReward",
}


def build_full_matrix_pairs() -> list[tuple]:
    """Return all 25 (condition, write, read, class) tuples in row-major order."""
    pairs = []
    for w, r in product(WRITE_ALGOS, READ_ALGOS):
        condition = f"D_{w}_{r}"
        interaction_class = KNOWN_CLASSES.get((w, r), "Unknown")
        pairs.append((condition, w, r, interaction_class))
    return pairs


def print_cost_estimate(iterations: int):
    """Print estimated API cost before running."""
    n_pairs = len(WRITE_ALGOS) * len(READ_ALGOS)
    avg_cost = 0.003      # $0.003/iter average (R2 pairs skew higher)
    r2_surcharge = 0.002  # R2 adds ~$0.002 extra per iter vs average
    n_r2_pairs = len(WRITE_ALGOS)  # 5 pairs involve R2

    base_cost   = n_pairs * iterations * avg_cost
    r2_extra    = n_r2_pairs * iterations * r2_surcharge
    total_low   = base_cost
    total_high  = base_cost + r2_extra
    judge_extra = n_pairs * iterations * 0.0005  # ~$0.0005/iter for LLM judge

    print("\n" + "=" * 60)
    print("EXPERIMENT D — COST ESTIMATE")
    print("=" * 60)
    print(f"  Combinations:           {n_pairs} (5 write × 5 read)")
    print(f"  Iterations per pair:    {iterations}")
    print(f"  Total iterations:       {n_pairs * iterations:,}")
    print(f"  Avg cost/iter:          $0.003 (agent sim + handoff)")
    print(f"  R2 surcharge (5 pairs): +$0.002/iter for summarization overhead")
    print(f"  LLM judge overhead:     +$0.0005/iter")
    print(f"  ---")
    print(f"  Estimated total (low):  ${total_low:.2f}")
    print(f"  Estimated total (high): ${total_high + judge_extra:.2f}")
    print(f"\n  Quick tiers:")
    for n in [10, 100, 1000]:
        lo = n_pairs * n * avg_cost
        hi = lo + n_r2_pairs * n * r2_surcharge + n_pairs * n * 0.0005
        print(f"    {n:>5} iters/pair → ${lo:.2f} – ${hi:.2f}")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Heatmap + 3D surface plots
# ---------------------------------------------------------------------------

def _build_matrix(df: pd.DataFrame, metric: str) -> tuple[np.ndarray, list, list]:
    """Build 5×5 numpy matrix for a given metric, rows=write, cols=read."""
    mat = np.full((5, 5), np.nan)
    for i, w in enumerate(WRITE_ALGOS):
        for j, r in enumerate(READ_ALGOS):
            cond = f"D_{w}_{r}"
            subset = df[df["condition"] == cond][metric].dropna()
            if not subset.empty:
                mat[i, j] = subset.median() if "latency" in metric else subset.mean()
    return mat, WRITE_ALGOS, READ_ALGOS


def plot_heatmap(df: pd.DataFrame, metric: str, output_dir: Path):
    try:
        import matplotlib.pyplot as plt
        import seaborn as sns
    except ImportError:
        logger.warning("matplotlib/seaborn not installed — skipping heatmap for %s", metric)
        return

    mat, write_labels, read_labels = _build_matrix(df, metric)

    fig, ax = plt.subplots(figsize=(9, 6))
    # Invert colormap for latency/cost (lower = better = green)
    cmap = "RdYlGn_r" if any(k in metric for k in ["latency", "cost", "bytes"]) else "RdYlGn"
    sns.heatmap(
        mat,
        annot=True,
        fmt=".2f",
        xticklabels=read_labels,
        yticklabels=write_labels,
        cmap=cmap,
        ax=ax,
        linewidths=0.5,
        cbar_kws={"label": metric},
    )
    ax.set_title(f"Experiment D: Write × Read — {metric}", fontsize=13, pad=12)
    ax.set_xlabel("Read Algorithm", fontsize=11)
    ax.set_ylabel("Write Algorithm", fontsize=11)

    # Annotate known interaction classes
    for (w, r), cls in KNOWN_CLASSES.items():
        i, j = WRITE_ALGOS.index(w), READ_ALGOS.index(r)
        short = {"HighlySynergistic": "★ SYN", "CatastrophicInterference": "✗ TOX",
                 "HighRiskHighReward": "⚡ HRR", "Baseline": "BASE"}.get(cls, "")
        if short:
            ax.text(j + 0.5, i + 0.85, short, ha="center", va="center",
                    fontsize=7, color="white", fontweight="bold")

    plt.tight_layout()
    out_path = output_dir / f"experiment_d_heatmap_{metric}.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info("Heatmap saved: %s", out_path)


def plot_surface(df: pd.DataFrame, metric: str, output_dir: Path):
    try:
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
    except ImportError:
        logger.warning("matplotlib not installed — skipping 3D surface for %s", metric)
        return

    mat, _, _ = _build_matrix(df, metric)

    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_subplot(111, projection="3d")

    x_idx = np.arange(len(READ_ALGOS))
    y_idx = np.arange(len(WRITE_ALGOS))
    X, Y = np.meshgrid(x_idx, y_idx)

    # Mask NaN cells (failed combinations like W1+R3 without sentence_transformers)
    Z = np.where(np.isnan(mat), 0, mat)

    surf = ax.plot_surface(X, Y, Z, cmap="RdYlGn_r", edgecolor="grey",
                           linewidth=0.3, alpha=0.85)
    fig.colorbar(surf, ax=ax, shrink=0.5, label=metric)

    ax.set_xticks(x_idx)
    ax.set_xticklabels(READ_ALGOS, fontsize=9)
    ax.set_yticks(y_idx)
    ax.set_yticklabels(WRITE_ALGOS, fontsize=9)
    ax.set_xlabel("Read Algorithm", labelpad=10)
    ax.set_ylabel("Write Algorithm", labelpad=10)
    ax.set_zlabel(metric, labelpad=10)
    ax.set_title(f"Experiment D: 3D Surface — {metric}", pad=15)

    out_path = output_dir / f"experiment_d_surface_{metric}.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info("3D surface saved: %s", out_path)


def print_compatibility_matrix(df: pd.DataFrame):
    """Print paper-ready 5×5 table with key metrics."""
    rows = []
    for w in WRITE_ALGOS:
        for r in READ_ALGOS:
            cond = f"D_{w}_{r}"
            subset = df[df["condition"] == cond]
            if subset.empty:
                rows.append({
                    "Write": w, "Read": r,
                    "Handoff p50 (ms)": "FAILED",
                    "Integrity": "—",
                    "Retrieval Acc.": "—",
                    "Cost/iter ($)": "—",
                    "Class": KNOWN_CLASSES.get((w, r), "—"),
                })
            else:
                rows.append({
                    "Write": w,
                    "Read": r,
                    "Handoff p50 (ms)": f"{subset['handoff_latency_ms'].median():.0f}",
                    "Integrity": f"{subset['state_integrity_score'].mean():.3f}",
                    "Retrieval Acc.": f"{subset['retrieval_accuracy_score'].mean():.3f}",
                    "Cost/iter ($)": f"{subset['estimated_cost_usd'].mean():.5f}",
                    "Class": KNOWN_CLASSES.get((w, r), ""),
                })

    display = pd.DataFrame(rows)
    print("\n" + "=" * 100)
    print("EXPERIMENT D: FULL WRITE × READ COMPATIBILITY SURFACE (5 × 5 = 25 COMBINATIONS)")
    print("=" * 100)
    print(display.to_string(index=False))
    print("=" * 100)

    # Highlight best and worst cells
    numeric = df.copy()
    if not numeric.empty:
        best_int = numeric.groupby("condition")["state_integrity_score"].mean().idxmax()
        worst_int = numeric.groupby("condition")["state_integrity_score"].mean().idxmin()
        best_lat = numeric.groupby("condition")["handoff_latency_ms"].median().idxmin()
        print(f"\n  Best integrity:        {best_int}")
        print(f"  Worst integrity:       {worst_int}  ← toxic interference candidate")
        print(f"  Lowest handoff p50:    {best_lat}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Experiment D: Full 5×5 Write×Read Compatibility Surface"
    )
    parser.add_argument(
        "--enabled",
        action="store_true",
        default=False,
        help="Must be set explicitly to run the experiment. "
             "Disabled by default due to API cost (~$0.75–$7.50 at 10–100 iters/pair).",
    )
    parser.add_argument("--iterations", type=int, default=100,
                        help="Iterations per W×R pair (25 pairs total)")
    parser.add_argument("--output", default="results/experiment_d")
    parser.add_argument("--redis-a-port", type=int, default=6379)
    parser.add_argument("--redis-b-port", type=int, default=6380)
    parser.add_argument("--cassandra-host", default="localhost")
    parser.add_argument("--model", default="claude-haiku-4-5")
    parser.add_argument("--skip-plots", action="store_true", default=False,
                        help="Skip heatmap and 3D surface generation")
    parser.add_argument("--surface-plots", action="store_true", default=False,
                        help="Also generate 3D surface plots (requires matplotlib mpl_toolkits)")
    args = parser.parse_args()

    # Guard: must pass --enabled explicitly
    if not args.enabled:
        print("\n" + "=" * 60)
        print("Experiment D is DISABLED by default.")
        print("")
        print("This experiment runs all 25 Write×Read combinations.")
        print("Pass --enabled to run it.")
        print("")
        print_cost_estimate(args.iterations)
        print("Usage:")
        print(f"  ANTHROPIC_API_KEY=sk-ant-... CASSANDRA_STUB=1 \\")
        print(f"  python -m experiments.run_experiment_d \\")
        print(f"    --enabled --iterations {args.iterations} \\")
        print(f"    --output {args.output}")
        print("=" * 60 + "\n")
        sys.exit(0)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs = build_full_matrix_pairs()
    print_cost_estimate(args.iterations)

    logger.info("=== Experiment D: Full Write×Read Compatibility Surface ===")
    logger.info("Pairs: %d  (5 write × 5 read)", len(pairs))
    logger.info("Iterations per pair: %d", args.iterations)
    logger.info("Total iterations: %d", len(pairs) * args.iterations)
    logger.info("Model: %s", args.model)
    logger.info("Output: %s", output_dir)

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

    # Save raw data
    csv_path = collector.save_csv("experiment_d_raw.csv")
    json_path = collector.save_json("experiment_d_raw.json")
    logger.info("Raw data saved: %s, %s", csv_path, json_path)

    # Summary per (write, read) pair
    summary = collector.summary_stats(group_by=["condition", "write_algorithm", "read_algorithm"])
    summary.to_csv(output_dir / "experiment_d_summary.csv", index=False)

    # Wilcoxon tests vs W0+R0 baseline
    all_conditions = [p[0] for p in pairs]
    comparison_labels = [c for c in all_conditions if c != "D_W0_R0"]
    for metric in [
        "handoff_latency_ms", "state_integrity_score",
        "retrieval_accuracy_score", "estimated_cost_usd",
        "execution_latency_ms", "context_token_count",
    ]:
        wtest = collector.wilcoxon_test(
            metric=metric,
            group_col="condition",
            baseline_label="D_W0_R0",
            comparison_labels=comparison_labels,
        )
        if not wtest.empty:
            wtest.to_csv(output_dir / f"wilcoxon_{metric}.csv", index=False)

    # Print compatibility matrix table
    df = collector.to_dataframe()
    print_compatibility_matrix(df)

    # Generate plots
    if not args.skip_plots:
        plot_metrics = [
            "handoff_latency_ms",
            "state_integrity_score",
            "retrieval_accuracy_score",
            "estimated_cost_usd",
        ]
        for metric in plot_metrics:
            plot_heatmap(df, metric, output_dir)
            if args.surface_plots:
                plot_surface(df, metric, output_dir)

    logger.info("Experiment D complete. Results in: %s", output_dir)


if __name__ == "__main__":
    main()
