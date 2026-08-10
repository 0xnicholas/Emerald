#!/usr/bin/env python3
"""Convert benchmark JSON report(s) to Markdown summary.

Usage:
    python scripts/benchmark_to_markdown.py <input.json> <output.md>
    python scripts/benchmark_to_markdown.py --dual --small <small.json> \\
        [--large <large.json>] --output <out.md>

Dual mode renders a per-dimension two-column comparison (3-small vs 3-large).
The ``--large`` report is optional: if the second model's run failed, its
column renders as unavailable (—) instead of the script crashing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_MISSING = "—"

# Metric keys in order of preference when picking "the" score of a
# benchmark for comparison tables.  Shared by single and dual renderers.
_KEY_METRICS = (
    "accuracy",
    "classification_accuracy",
    "update_detection_rate",
    "search_accuracy",
    "coverage",
    "latest_recall@1",
    "expired_exclusion_rate",
    "is_latest_flip_rate",
    "update_relation_rate",
    "overall_accuracy",
    "keep_rate",
    "forget_rate",
    "precision@1",
    "recall@5",
    "mrr",
)


def pick_key_metric(metrics: dict[str, Any]) -> tuple[str, Any] | None:
    """Return (key, value) of the most meaningful metric, if any."""
    for key in _KEY_METRICS:
        if key in metrics:
            return key, metrics[key]
    return None


def _fmt_score(value: Any) -> str:
    """Format a score cell; floats get 3 decimals, everything else is str()."""
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _model_label(report: dict[str, Any], fallback: str) -> str:
    """Column label from the report config, with a sane fallback.

    Old reports may predate the ``config.embedding_model`` field.
    """
    model = report.get("config", {}).get("embedding_model")
    return model if isinstance(model, str) and model else fallback


def _render_details(report: dict[str, Any]) -> list[str]:
    """Detail blocks for one report's results (shared by both renderers)."""
    lines: list[str] = []
    for r in report.get("results", []):
        lines.append(f"### {r.get('name', '?')}")
        lines.append(f"- **Aligns with:** {r.get('aligns_with', '?')}")
        lines.append(f"- **Description:** {r.get('description', '?')}")
        for k, v in r.get("metrics", {}).items():
            lines.append(f"- {k}: {_fmt_score(v)}")
        lines.append("")
    return lines


def render(report: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = report.get("summary", {})
    cfg = report.get("config", {})

    lines.append("# Emerald Benchmark Report\n")
    lines.append(f"**Generated:** {report.get('timestamp', 'unknown')}\n")
    lines.append(
        f"**Config:** embeddings={cfg.get('embeddings', '?')}, "
        f"embedding_dim={cfg.get('embedding_dim', '?')}, "
        f"llm_relationships={cfg.get('llm_relationships', False)}\n"
    )
    lines.append("## Summary\n")
    lines.append(
        f"- **Pass rate:** {summary.get('passed', 0)}/{summary.get('total', 0)} "
        f"= {summary.get('pass_rate', 0):.1%}"
    )
    lines.append(
        f"- **Aggregate score:** {summary.get('aggregate_score', 0):.3f}\n"
    )
    lines.append("## Per-benchmark Results\n")
    lines.append("| Benchmark | Status | Key metric |")
    lines.append("|---|---|---|")

    for r in report.get("results", []):
        picked = pick_key_metric(r.get("metrics", {}))
        if picked is not None:
            key, value = picked
            key_metric = f"{key}={_fmt_score(value)}"
        else:
            key_metric = "(no metric)"
        passed = "✅" if r.get("passed") else "❌"
        lines.append(f"| {r.get('name', '?')} | {passed} | {key_metric} |")

    lines.append("\n## Details\n")
    lines.extend(_render_details(report))
    return "\n".join(lines) + "\n"


def render_dual(small: dict[str, Any], large: dict[str, Any] | None) -> str:
    """Render a two-model comparison (text-embedding-3-small vs -large).

    ``large`` may be ``None`` when the second model's run failed or is
    missing — its column then renders as unavailable instead of crashing.
    """
    small_label = _model_label(small, "text-embedding-3-small")
    small_dim = small.get("config", {}).get("embedding_dim", "?")
    large_label = "text-embedding-3-large"
    large_dim = "?"

    lines: list[str] = []
    lines.append("# Emerald Benchmark Report — 双模型对照\n")
    if large is None:
        lines.append(
            f"> ⚠️ The second model run ({large_label}) failed or is missing — "
            f"its column renders as {_MISSING}.\n"
        )
    else:
        large_label = _model_label(large, "text-embedding-3-large")
        large_dim = large.get("config", {}).get("embedding_dim", "?")
    lines.append(
        f"**Models:** {small_label} ({small_dim} dims) vs "
        f"{large_label} ({large_dim} dims)\n"
    )

    # ── Summary ──────────────────────────────────────────────────────────
    lines.append("## Summary\n")
    lines.append("| Model | Pass rate | Aggregate score |")
    lines.append("|---|---|---|")

    def _summary_row(report: dict[str, Any], label: str) -> str:
        summary = report.get("summary", {})
        passed = summary.get("passed", 0)
        total = summary.get("total", 0)
        rate = summary.get("pass_rate", 0.0)
        agg = summary.get("aggregate_score", 0.0)
        rate_s = f"{rate:.1%}" if isinstance(rate, float) else str(rate)
        return f"| {label} | {passed}/{total} = {rate_s} | {agg:.3f} |"

    lines.append(_summary_row(small, small_label))
    if large is not None:
        lines.append(_summary_row(large, large_label))
    lines.append("")

    # ── Per-dimension two-column comparison ──────────────────────────────
    small_by_name = {r.get("name", "?"): r for r in small.get("results", [])}
    large_by_name = (
        {r.get("name", "?"): r for r in large.get("results", [])}
        if large is not None
        else {}
    )
    # Union of dimensions, small report first (its order is the canonical one)
    all_names = list(dict.fromkeys([*small_by_name.keys(), *large_by_name.keys()]))

    lines.append("## Per-Dimension Comparison\n")
    lines.append(f"| Dimension | {small_label} | {large_label} | Δ |")
    lines.append("|---|---|---|---|")

    for name in all_names:
        small_score = _key_score(small_by_name.get(name))
        large_score = _key_score(large_by_name.get(name))
        small_cell = _fmt_score(small_score) if small_score is not None else _MISSING
        large_cell = _fmt_score(large_score) if large_score is not None else _MISSING
        diff = _MISSING
        if (
            small_score is not None
            and large_score is not None
            and isinstance(small_score, (int, float))
            and isinstance(large_score, (int, float))
        ):
            diff = f"{large_score - small_score:+.3f}"
        lines.append(f"| {name} | {small_cell} | {large_cell} | {diff} |")
    lines.append("")

    # ── Details per model ────────────────────────────────────────────────
    lines.append("## Details\n")
    lines.append(f"### {small_label}\n")
    lines.extend(_render_details(small))
    if large is not None:
        lines.append(f"### {large_label}\n")
        lines.extend(_render_details(large))
    return "\n".join(lines) + "\n"


def _key_score(result: dict[str, Any] | None) -> Any:
    """The picked key metric value for a result row, or None."""
    if result is None:
        return None
    picked = pick_key_metric(result.get("metrics", {}))
    return picked[1] if picked else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert benchmark JSON report(s) to Markdown summary."
    )
    parser.add_argument("input", nargs="?", help="single mode: input JSON")
    parser.add_argument("output", nargs="?", help="single mode: output Markdown")
    parser.add_argument("--dual", action="store_true",
                        help="two-model comparison mode")
    parser.add_argument("--small", help="dual mode: first model's JSON report")
    parser.add_argument("--large", help=(
        "dual mode: second model's JSON report (optional — a missing "
        "report renders its column as unavailable)")
    )
    parser.add_argument("--output", dest="out_path",
                        help="dual mode: output Markdown path")
    args = parser.parse_args()

    if args.dual:
        if not args.small or not args.out_path:
            parser.error("--dual requires --small and --output")
        small = json.loads(Path(args.small).read_text())
        large = None
        if args.large:
            large = json.loads(Path(args.large).read_text())
        dst = Path(args.out_path)
        dst.write_text(render_dual(small, large))
    else:
        if not args.input or not args.output:
            print(
                f"Usage: {sys.argv[0]} <input.json> <output.md>",
                file=sys.stderr,
            )
            return 1
        report = json.loads(Path(args.input).read_text())
        dst = Path(args.output)
        dst.write_text(render(report))

    print(f"Wrote {dst} ({dst.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
