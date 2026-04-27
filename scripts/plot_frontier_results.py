from __future__ import annotations

"""Generate report-ready frontier figures
Reads a frontier export and writes cleaned matplotlib charts"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


def load_report(path: Path) -> dict:
    """Load a frontier report payload"""
    return json.loads(path.read_text())


def candidate_lookup(report: dict) -> dict[str, dict]:
    """Index candidates by id"""
    return {candidate["candidate_id"]: candidate for candidate in report["candidates"]}


def short_label(candidate_id: str) -> str:
    """Shorten candidate ids for labels"""
    if candidate_id == "baseline":
        return "baseline"
    return candidate_id.replace("candidate_", "c")


def apply_report_style() -> None:
    """Apply shared report styling"""
    plt.style.use("default")
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#3f3836",
            "axes.labelcolor": "#3f3836",
            "axes.titlecolor": "#2f2a28",
            "text.color": "#3f3836",
            "xtick.color": "#4a4341",
            "ytick.color": "#4a4341",
            "font.size": 11,
            "axes.titlesize": 16,
            "axes.labelsize": 12,
            "legend.fontsize": 10,
            "grid.color": "#d8cec8",
        }
    )


def compute_local_frontier_ids(items, *, get_item_id, dimensions, epsilon: float = 1e-9) -> set[str]:
    """Compute nondominated ids for plotted dimensions"""
    frontier_ids: set[str] = set()
    for item in items:
        dominated = False
        for other in items:
            if get_item_id(other) == get_item_id(item):
                continue

            not_worse = True
            strictly_better = False
            for _, direction, getter in dimensions:
                item_value = getter(item)
                other_value = getter(other)
                if direction == "max":
                    if other_value < (item_value - epsilon):
                        not_worse = False
                        break
                    if other_value > (item_value + epsilon):
                        strictly_better = True
                else:
                    if other_value > (item_value + epsilon):
                        not_worse = False
                        break
                    if other_value < (item_value - epsilon):
                        strictly_better = True

            if not_worse and strictly_better:
                dominated = True
                break

        if not dominated:
            frontier_ids.add(get_item_id(item))
    return frontier_ids


def frontier_tradeoff_plot(report: dict, output_dir: Path) -> Path:
    """Plot slot gain against additional token spend"""
    apply_report_style()
    candidates = report["candidates"]
    frontier_ids = compute_local_frontier_ids(
        candidates,
        get_item_id=lambda candidate: candidate["candidate_id"],
        dimensions=[
            ("slot_gain", "max", lambda candidate: candidate["objective_vector"]["global.slot_gain"]),
            ("token_delta", "max", lambda candidate: candidate["objective_vector"]["global.token_delta"]),
        ],
    )
    label_offsets = {
        "candidate_0027": (6, 8),
        "candidate_0040": (6, 8),
        "candidate_0028": (6, 8),
        "candidate_0017": (6, 8),
        "candidate_0018": (6, 8),
        "candidate_0035": (6, 8),
        "baseline": (6, -16),
    }

    xs = [-candidate["objective_vector"]["global.token_delta"] for candidate in candidates]
    ys = [candidate["objective_vector"]["global.slot_gain"] for candidate in candidates]
    colors = [candidate["utility_score"] for candidate in candidates]

    fig, ax = plt.subplots(figsize=(10, 6))
    scatter = ax.scatter(
        xs,
        ys,
        c=colors,
        cmap="copper",
        alpha=0.82,
        s=60,
        edgecolors="white",
        linewidths=0.7,
    )

    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        x = -candidate["objective_vector"]["global.token_delta"]
        y = candidate["objective_vector"]["global.slot_gain"]
        if candidate_id in frontier_ids:
            ax.scatter(
                [x],
                [y],
                s=170,
                facecolors="none",
                edgecolors="#8c3f2f",
                linewidths=1.8,
                zorder=3,
            )
            ax.annotate(
                short_label(candidate_id),
                (x, y),
                xytext=label_offsets.get(candidate_id, (6, 6)),
                textcoords="offset points",
                fontsize=9,
                color="#5b4038",
            )
        elif candidate_id == "baseline":
            ax.scatter(
                [x],
                [y],
                s=160,
                marker="D",
                color="#2f5d62",
                edgecolors="white",
                linewidths=0.9,
                zorder=3,
            )
            ax.annotate(
                "baseline",
                (x, y),
                xytext=label_offsets["baseline"],
                textcoords="offset points",
                fontsize=9,
                color="#2f5d62",
            )

    ax.set_title("Pareto Frontier: Slot Gain vs. Extra Retrieved Tokens", pad=14)
    ax.set_xlabel("Extra Retrieved Tokens vs. Flat Baseline\n(higher means hierarchy retrieved more tokens)")
    ax.set_ylabel("Global Slot Gain")
    ax.grid(alpha=0.18, linestyle="--", linewidth=0.8)

    cbar = fig.colorbar(scatter, ax=ax)
    cbar.set_label("Utility Score")

    legend_handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#b88564", markeredgecolor="white", markersize=8, label="candidate"),
        Line2D([0], [0], marker="o", color="#8c3f2f", markerfacecolor="none", markersize=10, linewidth=0, markeredgewidth=1.8, label="frontier"),
        Line2D([0], [0], marker="D", color="none", markerfacecolor="#2f5d62", markeredgecolor="white", markersize=8, label="baseline"),
    ]
    ax.legend(handles=legend_handles, frameon=False, loc="lower right")

    out_path = output_dir / "frontier_tradeoff.png"
    fig.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out_path


def recall_tradeoff_plot(report: dict, output_dir: Path) -> Path:
    """Plot keyword gain against slot gain"""
    apply_report_style()
    candidates = report["candidates"]
    frontier_ids = compute_local_frontier_ids(
        candidates,
        get_item_id=lambda candidate: candidate["candidate_id"],
        dimensions=[
            ("keyword_gain", "max", lambda candidate: candidate["objective_vector"]["global.keyword_gain"]),
            ("slot_gain", "max", lambda candidate: candidate["objective_vector"]["global.slot_gain"]),
        ],
    )
    label_offsets = {
        "candidate_0027": (6, 8),
        "candidate_0040": (6, 8),
        "candidate_0028": (6, 8),
        "candidate_0017": (6, -12),
        "candidate_0018": (6, 8),
        "candidate_0035": (6, 8),
        "baseline": (6, 8),
    }

    fig, ax = plt.subplots(figsize=(10, 6))
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        vector = candidate["objective_vector"]
        x = vector["global.keyword_gain"]
        y = vector["global.slot_gain"]
        is_baseline = candidate_id == "baseline"
        is_frontier = candidate_id in frontier_ids
        marker = "D" if is_baseline else "o"
        color = "#2f5d62" if is_baseline else "#c97a63"
        alpha = 0.95 if (is_frontier or is_baseline) else 0.24
        size = 74 if is_frontier else 42
        ax.scatter(x, y, marker=marker, s=size, color=color, alpha=alpha, edgecolors="white", linewidths=0.7)
        if is_frontier:
            ax.scatter(
                [x],
                [y],
                s=150,
                facecolors="none",
                edgecolors="#8c3f2f",
                linewidths=1.6,
                zorder=3,
            )
        if candidate_id in frontier_ids or candidate_id == "baseline":
            ax.annotate(
                short_label(candidate_id),
                (x, y),
                xytext=label_offsets.get(candidate_id, (6, 6)),
                textcoords="offset points",
                fontsize=9,
                color="#5b4038" if candidate_id != "baseline" else "#2f5d62",
            )

    ax.set_title("Recall Surface: Keyword Gain vs. Slot Gain", pad=14)
    ax.set_xlabel("Global Keyword Gain")
    ax.set_ylabel("Global Slot Gain")
    ax.grid(alpha=0.18, linestyle="--", linewidth=0.8)

    out_path = output_dir / "recall_surface.png"
    fig.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out_path


def slice_breakdown_plot(report: dict, output_dir: Path) -> Path:
    """Plot slice-level slot gain for leading candidates"""
    apply_report_style()
    candidates = candidate_lookup(report)
    slice_names = [slice_info["name"] for slice_info in report["slices"]]
    slice_frontier_ids = compute_local_frontier_ids(
        list(candidates.values()),
        get_item_id=lambda candidate: candidate["candidate_id"],
        dimensions=[
            (
                slice_name,
                "max",
                lambda candidate, slice_name=slice_name: candidate["slice_summaries"][slice_name]["avg_slot_recall_gain"],
            )
            for slice_name in slice_names
        ],
    )
    ranked_slice_frontier_ids = sorted(
        (candidate_id for candidate_id in slice_frontier_ids if candidate_id != "baseline"),
        key=lambda candidate_id: sum(
            candidates[candidate_id]["slice_summaries"][slice_name]["avg_slot_recall_gain"] for slice_name in slice_names
        ),
        reverse=True,
    )
    chosen_ids = ranked_slice_frontier_ids[:3]
    if "baseline" in candidates:
        chosen_ids.append("baseline")

    positions = list(range(len(slice_names)))

    fig, ax = plt.subplots(figsize=(10.5, 6))
    palette = ["#a95f4a", "#cf8c73", "#e2b48c", "#2f5d62"]
    all_values: list[float] = []

    for idx, candidate_id in enumerate(chosen_ids):
        candidate = candidates[candidate_id]
        values = [candidate["slice_summaries"][slice_name]["avg_slot_recall_gain"] for slice_name in slice_names]
        all_values.extend(values)
        linestyle = "--" if candidate_id == "baseline" else "-"
        marker = "D" if candidate_id == "baseline" else "o"
        ax.plot(
            positions,
            values,
            label=short_label(candidate_id),
            color=palette[idx % len(palette)],
            linewidth=2.2,
            marker=marker,
            markersize=7,
            linestyle=linestyle,
        )

    y_min = min(all_values)
    y_max = max(all_values)
    padding = max((y_max - y_min) * 0.4, 0.0025)

    ax.set_title("Slice-Level Slot Gain by Candidate", pad=14)
    ax.set_ylabel("Average Slot Recall Gain")
    ax.set_xticks(positions)
    ax.set_xticklabels(["canonical", "unseen\nseeds", "hard\nperturbations"])
    ax.set_ylim(y_min - padding, y_max + padding)
    ax.grid(axis="y", alpha=0.18, linestyle="--", linewidth=0.8)
    ax.legend(frameon=False, ncols=len(chosen_ids), loc="upper left")

    out_path = output_dir / "slice_breakdown.png"
    fig.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out_path


def stability_modes_plot(report: dict, output_dir: Path) -> Path:
    """Plot stability mode frequency and centroids"""
    apply_report_style()
    modes = report["stability_report"]["modes"]
    mode_ids = [mode["mode_id"] for mode in modes]
    appearance = [mode["appearance_rate"] for mode in modes]
    slot_gain = [mode["centroid_objectives"]["global.slot_gain"] for mode in modes]
    extra_tokens = [-mode["centroid_objectives"]["global.token_delta"] for mode in modes]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))

    axes[0].bar(mode_ids, appearance, color="#c97a63")
    axes[0].set_title("Mode Stability Across Optimization Runs")
    axes[0].set_ylabel("Appearance Rate")
    axes[0].set_ylim(0, 1.05)
    axes[0].grid(axis="y", alpha=0.18, linestyle="--", linewidth=0.8)

    right_axis = axes[1].twinx()
    slot_line = axes[1].plot(mode_ids, slot_gain, marker="o", color="#8c3f2f", linewidth=2.2, label="slot gain")
    token_line = right_axis.plot(
        mode_ids,
        extra_tokens,
        marker="D",
        color="#2f5d62",
        linewidth=2.2,
        label="extra retrieved tokens",
    )
    axes[1].set_title("Centroid Objectives by Stability Mode")
    axes[1].set_ylabel("Slot Gain", color="#8c3f2f")
    right_axis.set_ylabel("Extra Retrieved Tokens", color="#2f5d62")
    axes[1].tick_params(axis="y", colors="#8c3f2f")
    right_axis.tick_params(axis="y", colors="#2f5d62")
    axes[1].grid(alpha=0.18, linestyle="--", linewidth=0.8)
    axes[1].legend(slot_line + token_line, ["slot gain", "extra retrieved tokens"], frameon=False, loc="lower left")

    out_path = output_dir / "stability_modes.png"
    fig.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out_path


def write_summary(report: dict, output_dir: Path, generated_files: list[Path]) -> Path:
    """Write a small export manifest"""
    summary = report["summary"]
    lines = [
        "# Frontier Plot Export",
        "",
        f"- Source report: `reports/frontier_mvp_rigorous.json`",
        f"- Candidates evaluated: {summary['candidate_count']}",
        f"- Frontier size: {summary['frontier_count']}",
        f"- Global slot gain mean: {summary['global_slot_gain_mean']:.3f}",
        f"- Global keyword gain mean: {summary['global_keyword_gain_mean']:.3f}",
        f"- Global token delta mean: {summary['global_token_delta_mean']:.3f}",
        f"- Mean extra retrieved tokens vs. flat baseline: {-summary['global_token_delta_mean']:.3f}",
        "",
        "## Generated Files",
        "",
    ]
    lines.extend([f"- `{path.name}`" for path in generated_files])
    lines.append("")

    out_path = output_dir / "README.md"
    out_path.write_text("\n".join(lines))
    return out_path


def parse_args() -> argparse.Namespace:
    """Parse cli arguments"""
    parser = argparse.ArgumentParser(description="Generate matplotlib plots from a frontier sweep report.")
    parser.add_argument(
        "--input",
        default="reports/frontier_mvp_rigorous.json",
        help="Path to a frontier sweep JSON artifact.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/frontier_mvp_rigorous_figures",
        help="Directory where PNG plots should be written.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the figure export cli"""
    args = parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = load_report(input_path)

    generated = [
        frontier_tradeoff_plot(report, output_dir),
        recall_tradeoff_plot(report, output_dir),
        slice_breakdown_plot(report, output_dir),
        stability_modes_plot(report, output_dir),
    ]
    summary_path = write_summary(report, output_dir, generated)

    print(f"Wrote {len(generated)} plots to {output_dir}")
    for path in generated:
        print(path)
    print(summary_path)


if __name__ == "__main__":
    main()
