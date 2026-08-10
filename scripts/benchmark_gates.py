#!/usr/bin/env python3
"""Dual-gate evaluation for benchmark reports (issue #19, T3).

Pure, IO-free gate logic:

  evaluate_gates(report, mock_baseline) -> GateResults

Two gates (spec #16 Implementation Decisions):

  • Release gate (发布门槛) — every dimension's real score must be
    >= its mock baseline (baseline = the committed mock report, which
    must contain all dimensions).
  • Pass gate (通过门槛) — Contradiction Chain >= 80% AND the 7-dimension
    equal-weight average >= 70% (equal weights are the default; weight
    schemes are out of this ticket's scope).

The per-dimension "score" is the same key metric the published tables
use (`pick_key_metric` in scripts/benchmark_to_markdown.py), so the
gate conclusion matches what readers see in the report.

Loading the mock baseline (the only IO here, kept out of the pure
function):

  load_mock_baseline(path=None) -> dict

  Default path: docs/benchmarks/mock-baseline.json (committed, since
  reports/ is gitignored).  Missing file / invalid JSON / missing
  results list raise GateEvaluationError with an actionable message.

Updating the committed baseline:

  python scripts/run_benchmarks.py --mock
  cp reports/benchmark-<ts>.json docs/benchmarks/mock-baseline.json

CLI:

  python scripts/benchmark_gates.py <real-report.json> [--baseline <mock.json>]
  exit 0 = both gates pass, 1 = a gate fails, 2 = evaluation error.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add project root to path for direct script execution
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.benchmark_to_markdown import pick_key_metric

# ── Gate configuration (spec #16) ────────────────────────────────────────
PASS_GATE_CC_THRESHOLD = 0.8  # 矛盾链 ≥ 80%
PASS_GATE_AVG_THRESHOLD = 0.7  # 7 维等权均分 ≥ 70%
# The average is computed as sum/len over decimal metrics; a value that
# should be exactly 0.70 can round a hair below in binary floating point.
# A 1e-9 tolerance keeps the "恰好 70% 通过" boundary stable without
# materially loosening the gate.
_AVG_EPSILON = 1e-9
CC_DIMENSION_NAME = "Contradiction Chain"
DEFAULT_MOCK_BASELINE_PATH = (
    Path(__file__).parent.parent / "docs" / "benchmarks" / "mock-baseline.json"
)


class GateEvaluationError(ValueError):
    """Raised when a report or baseline cannot be evaluated.

    Covers: missing baseline file, invalid JSON, missing ``results``
    list, missing dimensions, and dimensions without a pickable score.
    """


# ── Pure gate logic ──────────────────────────────────────────────────────


@dataclass
class DimensionComparison:
    """Release-gate comparison for a single dimension."""

    name: str
    score: float
    baseline: float
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "baseline": self.baseline,
            "passed": self.passed,
        }


@dataclass
class GateResults:
    """Dual-gate conclusion. ``release_passed`` and ``pass_gate_passed``
    are independent: a run can be releasable but not pass, or vice versa."""

    release_passed: bool
    dimensions: list[DimensionComparison]
    pass_gate_passed: bool
    contradiction_chain_score: float
    average_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_gate": {
                "passed": self.release_passed,
                "dimensions": [d.to_dict() for d in self.dimensions],
            },
            "pass_gate": {
                "passed": self.pass_gate_passed,
                "contradiction_chain_score": self.contradiction_chain_score,
                "contradiction_chain_threshold": PASS_GATE_CC_THRESHOLD,
                "average_score": self.average_score,
                "average_threshold": PASS_GATE_AVG_THRESHOLD,
            },
        }


def _dimension_scores(report: dict[str, Any]) -> dict[str, tuple[str, float]]:
    """Map dimension name → (picked key, score), validating structure.

    Pure: operates on the report dict only; raises GateEvaluationError
    with the offending dimension named.  Duplicate dimension names and
    malformed result entries are rejected instead of silently misread.
    """
    results = report.get("results")
    if not isinstance(results, list):
        raise GateEvaluationError("报告缺少 results 列表，无法评估门槛")

    scores: dict[str, tuple[str, float]] = {}
    for result in results:
        if not isinstance(result, dict):
            raise GateEvaluationError(f"报告 results 条目不是对象（{result!r}）")
        name = result.get("name")
        if not isinstance(name, str) or not name:
            raise GateEvaluationError("报告结果条目缺少 name 字段")
        if name in scores:
            raise GateEvaluationError(f"报告维度重复: {name}")
        metrics = result.get("metrics")
        if not isinstance(metrics, dict):
            raise GateEvaluationError(f"维度 {name} 的 metrics 不是对象（{metrics!r}）")
        picked = pick_key_metric(metrics)
        if picked is None:
            raise GateEvaluationError(f"维度 {name} 没有可比较的关键指标（_KEY_METRICS 之外）")
        key, value = picked
        if not isinstance(value, (int, float)):
            raise GateEvaluationError(f"维度 {name} 的关键指标 {key} 不是数值（{value!r}）")
        scores[name] = (key, float(value))
    return scores


def evaluate_gates(report: dict[str, Any], mock_baseline: dict[str, Any]) -> GateResults:
    """Evaluate both gates. Pure: no IO, no external dependencies.

    Args:
        report: the run under evaluation (its ``results`` carry the
            per-dimension key metrics).
        mock_baseline: the committed mock report (same shape).

    Raises:
        GateEvaluationError: dimension sets differ, a dimension has no
            pickable score, or the pass gate's Contradiction Chain
            dimension is missing.
    """
    real = _dimension_scores(report)
    baseline = _dimension_scores(mock_baseline)

    missing_in_report = sorted(set(baseline) - set(real))
    missing_in_baseline = sorted(set(real) - set(baseline))
    if missing_in_report or missing_in_baseline:
        raise GateEvaluationError(
            "真实报告与 mock 基线的维度集合不一致: "
            f"真实报告缺少 {missing_in_report}, "
            f"基线缺少 {missing_in_baseline}"
        )

    # Release gate: every dimension >= its mock baseline, comparing the
    # same picked key metric on both sides (a divergent metric set would
    # silently compare apples to oranges).
    comparisons = []
    for name in real:  # report order preserved
        real_key, real_score = real[name]
        base_key, base_score = baseline[name]
        if real_key != base_key:
            raise GateEvaluationError(
                f"维度 {name} 两侧选中的关键指标不一致: 报告 {real_key} vs 基线 {base_key}"
            )
        comparisons.append(
            DimensionComparison(
                name=name,
                score=real_score,
                baseline=base_score,
                passed=real_score >= base_score,
            )
        )
    release_passed = all(c.passed for c in comparisons)

    # Pass gate: CC >= 80% AND 7-dim equal-weight average >= 70%.
    if CC_DIMENSION_NAME not in real:
        raise GateEvaluationError(f"通过门槛需要维度 {CC_DIMENSION_NAME!r}（矛盾链）")
    _cc_key, cc_score = real[CC_DIMENSION_NAME]
    average_score = sum(s for _, s in real.values()) / len(real)
    pass_gate_passed = (
        cc_score >= PASS_GATE_CC_THRESHOLD
        and average_score >= PASS_GATE_AVG_THRESHOLD - _AVG_EPSILON
    )

    return GateResults(
        release_passed=release_passed,
        dimensions=comparisons,
        pass_gate_passed=pass_gate_passed,
        contradiction_chain_score=cc_score,
        average_score=average_score,
    )


# ── Baseline loading (the only IO; deliberately separate from the pure
#    function so the gate logic stays deterministic and unit-testable) ─────


def _load_json_report(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise GateEvaluationError(
            f"{label}文件不存在: {path}。"
            "先运行 `python scripts/run_benchmarks.py --mock` 并把报告"
            "入库为 docs/benchmarks/mock-baseline.json"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateEvaluationError(f"{label}文件不是合法 JSON: {path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise GateEvaluationError(f"{label}文件必须是 JSON 对象: {path}")
    return data


def load_report(path: str | Path) -> dict[str, Any]:
    """Load a run's JSON report with a clear error on any IO problem."""
    return _load_json_report(Path(path), "报告")


def load_mock_baseline(path: str | Path | None = None) -> dict[str, Any]:
    """Load the committed mock baseline report.

    Defaults to ``DEFAULT_MOCK_BASELINE_PATH`` (docs/benchmarks/
    mock-baseline.json).  Raises GateEvaluationError when the file is
    missing, malformed, or lacks a ``results`` list.
    """
    baseline_path = Path(path) if path else DEFAULT_MOCK_BASELINE_PATH
    data = _load_json_report(baseline_path, "mock 基线")
    if not isinstance(data.get("results"), list):
        raise GateEvaluationError(f"mock 基线文件缺少 results 列表: {baseline_path}")
    return data


# ── CLI ──────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="评估基准跑分双门槛（发布门槛 + 通过门槛）")
    parser.add_argument("report", help="真实嵌入跑分 JSON 报告路径")
    parser.add_argument(
        "--baseline",
        default=None,
        help=f"mock 基线 JSON 路径（默认 {DEFAULT_MOCK_BASELINE_PATH}）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出门槛结论",
    )
    args = parser.parse_args(argv)

    try:
        report = load_report(args.report)
        baseline = load_mock_baseline(args.baseline)
        result = evaluate_gates(report, baseline)
    except GateEvaluationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print("发布门槛（每维真实分数 ≥ mock 基线）:")
        for d in result.dimensions:
            mark = "✅" if d.passed else "❌"
            print(f"  {mark} {d.name}: {d.score:.3f} vs 基线 {d.baseline:.3f}")
        print(f"  => {'通过' if result.release_passed else '不通过'}")
        print("通过门槛（矛盾链 ≥ 80% 且 7 维等权均分 ≥ 70%）:")
        print(f"  矛盾链: {result.contradiction_chain_score:.3f} / 0.800")
        print(f"  等权均分: {result.average_score:.3f} / 0.700")
        print(f"  => {'通过' if result.pass_gate_passed else '不通过'}")

    return 0 if (result.release_passed and result.pass_gate_passed) else 1


if __name__ == "__main__":
    sys.exit(main())
