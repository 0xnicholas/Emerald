#!/usr/bin/env python3
"""Convert benchmark JSON report(s) to Markdown summary.

Usage:
    python scripts/benchmark_to_markdown.py <input.json> <output.md>
    python scripts/benchmark_to_markdown.py --dual --small <small.json> \\
        [--large <large.json>] --output <out.md>
    python scripts/benchmark_to_markdown.py --absolute --small <small.json> \\
        [--large <large.json>] --baseline <mock.json> --output <out.md>

Dual mode renders a per-dimension two-column comparison (3-small vs 3-large).
The ``--large`` report is optional: if the second model's run failed, its
column renders as unavailable (—) instead of the script crashing.

Absolute mode (issue #20, T4) renders the date-named absolute-score report:
per-dimension three-column comparison (3-small / 3-large / mock baseline),
dual-gate conclusions (release gate + pass gate, via scripts.benchmark_gates),
a contradiction-chain dimension note, and independent-suite / ADR-0001
references.  The mock baseline defaults to the committed
``docs/benchmarks/mock-baseline.json``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Add project root to path for direct script execution (mirrors
# scripts/benchmark_gates.py; needed for the lazy ``scripts.benchmark_gates``
# import below — a top-level import would be circular).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


def render_absolute(
    small: dict[str, Any],
    large: dict[str, Any] | None,
    mock_baseline: dict[str, Any],
) -> str:
    """Render the absolute-score report (spec #16, issue #20 T4).

    Sections: summary, per-dimension three-column comparison (3-small /
    3-large / mock baseline), dual-gate conclusions (release gate +
    pass gate, evaluated per real model via ``evaluate_gates``),
    contradiction-chain dimension note, and independent-suite (ADR-0001)
    references.

    ``large`` may be ``None`` when the second model's run failed — its
    column renders as unavailable and only the small run is gate-evaluated.

    Raises GateEvaluationError when the real report and the mock baseline
    disagree on dimensions — a stale baseline must fail loudly instead of
    silently dropping a column from the conclusions.
    """
    # Lazy import: benchmark_gates imports this module for pick_key_metric,
    # so a module-level import here would be circular.
    from scripts.benchmark_gates import (
        PASS_GATE_AVG_THRESHOLD,
        PASS_GATE_CC_THRESHOLD,
        GateResults,
        evaluate_gates,
    )

    small_label = _model_label(small, "text-embedding-3-small")
    small_dim = small.get("config", {}).get("embedding_dim", "?")
    large_label = "text-embedding-3-large"
    large_dim = "?"
    if large is not None:
        large_label = _model_label(large, "text-embedding-3-large")
        large_dim = large.get("config", {}).get("embedding_dim", "?")
    date = str(small.get("timestamp", "unknown"))[:10]

    # Gates first: a stale/mismatched baseline must fail before any output.
    evaluations: list[tuple[str, GateResults]] = [
        (small_label, evaluate_gates(small, mock_baseline)),
    ]
    if large is not None:
        evaluations.append((large_label, evaluate_gates(large, mock_baseline)))

    lines: list[str] = []
    lines.append("# Emerald 绝对分报告\n")
    lines.append(f"**日期:** {date}（3-small 跑分时间戳）\n")
    lines.append(
        f"**模型:** {small_label} ({small_dim} dims)"
        + (f" vs {large_label} ({large_dim} dims)" if large is not None else "")
        + "\n"
    )
    lines.append(
        "**对比基线:** mock 嵌入（`docs/benchmarks/mock-baseline.json`，"
        "双门槛同源）\n"
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

    # ── Per-dimension three-column comparison ────────────────────────────
    small_by_name = {r.get("name", "?"): r for r in small.get("results", [])}
    large_by_name = (
        {r.get("name", "?"): r for r in large.get("results", [])}
        if large is not None
        else {}
    )
    baseline_by_name = {
        r.get("name", "?"): r for r in mock_baseline.get("results", [])
    }
    # Union of dimensions, small report first (canonical order); the gate
    # dimension-set check already ran, so every row has a baseline score.
    all_names = list(dict.fromkeys([*small_by_name.keys(), *large_by_name.keys()]))

    lines.append("## 每维度三列对比\n")
    lines.append(
        f"| Dimension | {small_label} | {large_label} | Mock 基线 | Δ |"
    )
    lines.append("|---|---|---|---|---|")

    for name in all_names:
        small_score = _key_score(small_by_name.get(name))
        large_score = _key_score(large_by_name.get(name))
        base_score = _key_score(baseline_by_name.get(name))
        small_cell = _fmt_score(small_score) if small_score is not None else _MISSING
        large_cell = _fmt_score(large_score) if large_score is not None else _MISSING
        base_cell = _fmt_score(base_score) if base_score is not None else _MISSING
        diff = _MISSING
        if (
            small_score is not None
            and large_score is not None
            and isinstance(small_score, (int, float))
            and isinstance(large_score, (int, float))
        ):
            diff = f"{large_score - small_score:+.3f}"
        lines.append(
            f"| {name} | {small_cell} | {large_cell} | {base_cell} | {diff} |"
        )
    lines.append("")

    # ── Dual-gate conclusions ────────────────────────────────────────────
    lines.append("## 双门槛结论\n")
    lines.append(
        "| 模型 | 发布门槛（每维 ≥ mock 基线） | "
        f"通过门槛（矛盾链 ≥ {PASS_GATE_CC_THRESHOLD:.0%} 且 "
        f"7 维等权均分 ≥ {PASS_GATE_AVG_THRESHOLD:.0%}） |"
    )
    lines.append("|---|---|---|")
    for label, gates in evaluations:
        release = "✅ 通过" if gates.release_passed else "❌ 不通过"
        pass_gate = "✅ 通过" if gates.pass_gate_passed else "❌ 不通过"
        lines.append(f"| {label} | {release} | {pass_gate} |")
    lines.append("")
    if large is None:
        lines.append(f"> ⚠️ {large_label} 跑分缺失，未评估其门槛。\n")

    failed = [
        (label, d.name, d.score, d.baseline)
        for label, gates in evaluations
        for d in gates.dimensions
        if not d.passed
    ]
    if failed:
        lines.append("发布门槛未通过维度：\n")
        for label, name, score, base in failed:
            lines.append(
                f"- ❌ {name}（{label}）: {_fmt_score(score)} < 基线 {_fmt_score(base)}"
            )
    else:
        lines.append("发布门槛：全部维度 ≥ mock 基线。\n")

    lines.append("通过门槛明细：\n")
    for label, gates in evaluations:
        lines.append(
            f"- {label}: 矛盾链 {gates.contradiction_chain_score:.3f} / "
            f"{PASS_GATE_CC_THRESHOLD:.3f} · 等权均分 "
            f"{gates.average_score:.3f} / {PASS_GATE_AVG_THRESHOLD:.3f}"
        )
    lines.append("")

    # ── Contradiction-chain dimension note ───────────────────────────────
    lines.append("## 矛盾链维度说明\n")
    lines.append(
        "**Contradiction Chain**（第 7 维度，issue #17 T1）：多轮取代对抗场景，"
        "5 条链 × 5 轮连续取代，每轮对同一实体的事实写入完全矛盾的新事实"
        "（结构模板换填充 / 数值变更 / 矛盾措辞三类语料，规则分类器在 mock 下"
        "确定性输出 UPDATES）。每轮验证：旧事实 `is_latest` 翻转为 False 且 "
        "`replaced_by` 指向新事实、UPDATES 边由新指向旧、最新事实按精确文本"
        "查询命中 top-1、过期事实不再被召回。指标：`latest_recall@1` / "
        "`expired_exclusion_rate` / `is_latest_flip_rate` / `update_relation_rate` "
        "/ `overall_accuracy`。\n"
    )

    # ── Independent suites & ADR-0001 ────────────────────────────────────
    lines.append("## 独立侧套件与依据\n")
    lines.append(
        "- **独立侧套件**（ADR-0001）：`tests/quality/temporal/`（"
        "`test_temporal_correctness.py` / `test_forgetting_effectiveness.py` / "
        "`test_graph_relationship_precision.py` / `test_neo4j_quality_variants.py`）"
        "——独立于本报告语料与指标，互不背书。\n"
    )
    lines.append(
        "- **ADR-0001**（[度量体系：绝对分与独立侧套件]"
        "(../adr/0001-metrics-absolute-scores-and-independent-suites.md)）："
        "绝对分只对自己负责，Emerald 不背书参照系的基准声明。\n"
    )
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
                        help="dual/absolute mode: output Markdown path")
    parser.add_argument(
        "--absolute",
        action="store_true",
        help="absolute-score report mode: three-column comparison "
             "(3-small / 3-large / mock baseline) + dual-gate conclusions",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="absolute mode: mock baseline JSON "
             "(default: docs/benchmarks/mock-baseline.json)",
    )
    args = parser.parse_args()

    if args.absolute:
        if not args.small or not args.out_path:
            parser.error("--absolute requires --small and --output")
        from scripts.benchmark_gates import GateEvaluationError, load_mock_baseline

        try:
            small = json.loads(Path(args.small).read_text())
            large = None
            if args.large:
                large = json.loads(Path(args.large).read_text())
            baseline = load_mock_baseline(args.baseline)
            dst = Path(args.out_path)
            dst.write_text(render_absolute(small, large, baseline))
        except GateEvaluationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    elif args.dual:
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
