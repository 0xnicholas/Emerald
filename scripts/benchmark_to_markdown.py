#!/usr/bin/env python3
"""Convert benchmark JSON report to Markdown summary.

Usage:
    python scripts/benchmark_to_markdown.py <input.json> <output.md>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def render(report: dict) -> str:
    lines: list[str] = []
    summary = report.get("summary", {})
    cfg = report.get("config", {})

    lines.append("# Emerald Benchmark Report\n")
    lines.append(
        f"**Generated:** {report.get('timestamp', 'unknown')}\n"
    )
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
        metrics = r.get("metrics", {})
        # Pick the most meaningful metric per benchmark
        key_metric = "(no metric)"
        for key in (
            "accuracy",
            "classification_accuracy",
            "update_detection_rate",
            "search_accuracy",
            "coverage",
            "overall_accuracy",
            "keep_rate",
            "forget_rate",
            "precision@1",
            "recall@5",
            "mrr",
        ):
            if key in metrics:
                key_metric = f"{key}={metrics[key]:.3f}"
                break
        passed = "✅" if r.get("passed") else "❌"
        lines.append(f"| {r.get('name', '?')} | {passed} | {key_metric} |")

    lines.append("\n## Details\n")
    for r in report.get("results", []):
        lines.append(f"### {r.get('name', '?')}")
        lines.append(f"- **Aligns with:** {r.get('aligns_with', '?')}")
        lines.append(f"- **Description:** {r.get('description', '?')}")
        metrics = r.get("metrics", {})
        for k, v in metrics.items():
            if isinstance(v, float):
                lines.append(f"- {k}: {v:.3f}")
            else:
                lines.append(f"- {k}: {v}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) != 3:
        print(
            f"Usage: {sys.argv[0]} <input.json> <output.md>",
            file=sys.stderr,
        )
        return 1
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    report = json.loads(src.read_text())
    dst.write_text(render(report))
    print(f"Wrote {dst} ({dst.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
