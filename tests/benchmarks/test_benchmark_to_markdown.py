"""Rendering-layer tests for benchmark Markdown reports (issue #18, T2).

Covers the dual-model (3-small / 3-large) comparison renderer:
- both columns present
- one column missing (a model run failed) — must not crash

Plus the absolute-score report renderer (issue #20, T4):
- three-column comparison (3-small / 3-large / mock baseline)
- dual-gate conclusions (release gate / pass gate)
- missing 3-large fallback
- stale baseline must raise, not silently drop a dimension

Synthetic report dicts only; no network, no real benchmark runs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# scripts/ is not a package; add it to the import path like the CI jobs do.
# The repo root is needed too: the absolute renderer lazily imports
# scripts.benchmark_gates (which itself imports this module — a top-level
# import would be circular).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import benchmark_to_markdown  # noqa: E402

from scripts.benchmark_gates import GateEvaluationError  # noqa: E402


def make_report(
    model: str, dim: int, scores: dict[str, float]
) -> dict:
    """Build a synthetic benchmark report dict.

    Each dimension carries a single ``overall_accuracy`` metric, which is
    the first float metric the renderer's key-metric picker will choose.
    """
    results = []
    for name, score in scores.items():
        results.append(
            {
                "name": name,
                "aligns_with": "test",
                "description": f"{name} via {model}",
                "metrics": {"overall_accuracy": score, "total_cases": 10},
                "passed": score >= 0.5,
                "details": {},
            }
        )
    passed = sum(1 for r in results if r["passed"])
    return {
        "version": "2.0",
        "timestamp": "2026-08-10T00:00:00+00:00",
        "config": {
            "embeddings": "real",
            "embedding_model": model,
            "embedding_dim": dim,
            "llm_relationships": False,
        },
        "results": results,
        "summary": {
            "passed": passed,
            "total": len(results),
            "pass_rate": passed / len(results) if results else 0.0,
            "aggregate_score": 0.7,
        },
    }


def test_render_dual_both_columns_present():
    """Both models' columns and the per-dimension diff are rendered."""
    small = make_report(
        "text-embedding-3-small", 1536,
        {"Fact Recall": 0.800, "Temporal Updates": 0.700},
    )
    large = make_report(
        "text-embedding-3-large", 3072,
        {"Fact Recall": 0.900, "Temporal Updates": 0.600},
    )

    md = benchmark_to_markdown.render_dual(small, large)

    # Both model labels and dimensions present
    assert "text-embedding-3-small" in md
    assert "text-embedding-3-large" in md
    assert "Fact Recall" in md
    assert "Temporal Updates" in md
    # Per-model scores in the right columns
    assert "0.800" in md and "0.900" in md
    assert "0.700" in md and "0.600" in md
    # Diff column: 0.900-0.800=+0.100, 0.600-0.700=-0.100
    assert "+0.100" in md
    assert "-0.100" in md
    # Embedding dimensions recorded in the header
    assert "1536" in md and "3072" in md


def test_render_dual_tolerates_missing_large_column():
    """A failed 3-large run must not crash the renderer."""
    small = make_report("text-embedding-3-small", 1536, {"Fact Recall": 0.800})

    md = benchmark_to_markdown.render_dual(small, None)

    assert "text-embedding-3-small" in md
    assert "0.800" in md
    # The missing column is rendered as unavailable, not omitted silently
    assert "—" in md
    # And the situation is called out in the report
    assert "missing" in md.lower()


def test_render_dual_tolerates_dimension_missing_in_one_model():
    """A dimension absent from one model's report renders as unavailable."""
    small = make_report("text-embedding-3-small", 1536, {"Fact Recall": 0.800})
    # e.g. the Contradiction Chain dimension (T1) not yet in the other report
    large = make_report(
        "text-embedding-3-large", 3072,
        {"Fact Recall": 0.900, "Contradiction Chain": 0.850},
    )

    md = benchmark_to_markdown.render_dual(small, large)

    assert "Contradiction Chain" in md
    assert "0.850" in md
    assert "—" in md


def test_render_dual_model_labels_fallback_without_config_field():
    """Old reports without ``config.embedding_model`` still get labels."""
    report = make_report("text-embedding-3-small", 1536, {"Fact Recall": 0.800})
    del report["config"]["embedding_model"]

    md = benchmark_to_markdown.render_dual(report, None)

    assert "text-embedding-3-small" in md
    assert "0.800" in md


def test_main_dual_mode_writes_output(tmp_path, monkeypatch):
    """CLI dual mode merges two JSONs into one Markdown file."""
    small_path = tmp_path / "small.json"
    small_path.write_text(
        json.dumps(make_report("text-embedding-3-small", 1536, {"Fact Recall": 0.8}))
    )
    large_path = tmp_path / "large.json"
    large_path.write_text(
        json.dumps(make_report("text-embedding-3-large", 3072, {"Fact Recall": 0.9}))
    )
    out = tmp_path / "out.md"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_to_markdown.py",
            "--dual",
            "--small", str(small_path),
            "--large", str(large_path),
            "--output", str(out),
        ],
    )

    assert benchmark_to_markdown.main() == 0
    text = out.read_text()
    assert "text-embedding-3-small" in text
    assert "text-embedding-3-large" in text


def test_main_dual_mode_tolerates_missing_large(tmp_path, monkeypatch):
    """CLI dual mode without --large still produces a report."""
    small_path = tmp_path / "small.json"
    small_path.write_text(
        json.dumps(make_report("text-embedding-3-small", 1536, {"Fact Recall": 0.8}))
    )
    out = tmp_path / "out.md"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_to_markdown.py",
            "--dual",
            "--small", str(small_path),
            "--output", str(out),
        ],
    )

    assert benchmark_to_markdown.main() == 0
    assert "text-embedding-3-small" in out.read_text()


# ── Absolute-score report renderer (issue #20, T4) ────────────────────────

_THREE_DIMS = {
    "Fact Recall": 0.800,
    "Temporal Updates": 0.900,
    "Contradiction Chain": 0.850,
}


def make_mock_baseline(scores: dict[str, float]) -> dict:
    """Synthetic mock baseline report (same shape as a run report)."""
    return make_report("mock", 1536, scores)


def test_render_absolute_three_columns_and_gates_pass():
    """Three columns (3-small / 3-large / mock baseline) and passing
    dual-gate conclusions, plus the CC note and ADR/suite references."""
    small = make_report("text-embedding-3-small", 1536, _THREE_DIMS)
    large = make_report(
        "text-embedding-3-large", 3072,
        {"Fact Recall": 0.900, "Temporal Updates": 0.700,
         "Contradiction Chain": 0.900},
    )
    baseline = make_mock_baseline(
        {"Fact Recall": 0.133, "Temporal Updates": 0.700,
         "Contradiction Chain": 0.800}
    )

    md = benchmark_to_markdown.render_absolute(small, large, baseline)

    # Three-column table with header, per-dimension values and Δ
    assert (
        "| Dimension | text-embedding-3-small | text-embedding-3-large "
        "| Mock 基线 | Δ |" in md
    )
    assert "| Fact Recall | 0.800 | 0.900 | 0.133 | +0.100 |" in md
    # Δ direction is documented in the report
    assert "Δ = 3-large 分数 − 3-small 分数" in md
    # Dual-gate conclusions: both models pass both gates here
    assert "## 双门槛结论" in md
    assert "发布门槛" in md
    assert "通过门槛" in md
    assert md.count("✅ 通过") >= 4
    assert "全部维度 ≥ mock 基线" in md
    # Contradiction-chain dimension note
    assert "## 矛盾链维度说明" in md
    assert "5 轮连续取代" in md
    # Independent suite + ADR-0001 references
    assert "tests/quality/temporal/" in md
    assert "0001-metrics-absolute-scores-and-independent-suites.md" in md


def test_render_absolute_gate_failures_are_called_out():
    """A failing release gate names the offending dimension with numbers;
    a failing pass gate shows the CC score below threshold."""
    small = make_report(
        "text-embedding-3-small", 1536,
        {"Fact Recall": 0.100, "Temporal Updates": 0.900,
         "Contradiction Chain": 0.500},
    )
    large = make_report(
        "text-embedding-3-large", 3072,
        {"Fact Recall": 0.900, "Temporal Updates": 0.900,
         "Contradiction Chain": 0.900},
    )
    baseline = make_mock_baseline(
        {"Fact Recall": 0.133, "Temporal Updates": 0.700,
         "Contradiction Chain": 0.800}
    )

    md = benchmark_to_markdown.render_absolute(small, large, baseline)

    # Small: release ❌ (0.100 < 0.133) and pass gate ❌ (CC 0.500 < 0.800)
    assert "❌ 不通过" in md
    assert "- ❌ Fact Recall（text-embedding-3-small）: 0.100 < 基线 0.133" in md
    assert "0.500 / 0.800" in md
    # Large: both gates pass
    assert md.count("✅ 通过") >= 2


def test_render_absolute_missing_large_evaluates_small_only():
    """Without a 3-large run the column renders as unavailable and the
    gates are evaluated for the small run only."""
    small = make_report("text-embedding-3-small", 1536, _THREE_DIMS)
    baseline = make_mock_baseline(
        {"Fact Recall": 0.133, "Temporal Updates": 0.700,
         "Contradiction Chain": 0.800}
    )

    md = benchmark_to_markdown.render_absolute(small, None, baseline)

    assert "—" in md
    assert "✅ 通过" in md
    assert "未评估" in md
    # No Δ-direction note without a second model
    assert "Δ = 3-large 分数" not in md


def test_render_absolute_stale_baseline_raises():
    """A baseline missing a dimension must raise, not silently omit the
    column and produce a misleading conclusion."""
    small = make_report("text-embedding-3-small", 1536, _THREE_DIMS)
    stale = make_mock_baseline(
        {"Fact Recall": 0.133, "Temporal Updates": 0.700}  # no CC
    )

    with pytest.raises(GateEvaluationError):
        benchmark_to_markdown.render_absolute(small, None, stale)


def test_main_absolute_mode_writes_output(tmp_path, monkeypatch):
    """CLI --absolute renders the date-named report with gate conclusions."""
    small_path = tmp_path / "small.json"
    small_path.write_text(json.dumps(make_report(
        "text-embedding-3-small", 1536, _THREE_DIMS)))
    large_path = tmp_path / "large.json"
    large_path.write_text(json.dumps(make_report(
        "text-embedding-3-large", 3072,
        {"Fact Recall": 0.900, "Temporal Updates": 0.700,
         "Contradiction Chain": 0.900})))
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(make_mock_baseline(
        {"Fact Recall": 0.133, "Temporal Updates": 0.700,
         "Contradiction Chain": 0.800})))
    out = tmp_path / "absolute-scores-2026-08-10.md"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_to_markdown.py",
            "--absolute",
            "--small", str(small_path),
            "--large", str(large_path),
            "--baseline", str(baseline_path),
            "--output", str(out),
        ],
    )

    assert benchmark_to_markdown.main() == 0
    text = out.read_text()
    assert "每维度三列对比" in text
    assert "双门槛结论" in text
    assert "tests/quality/temporal/" in text


def test_main_absolute_mode_baseline_mismatch_exits_2(tmp_path, monkeypatch, capsys):
    """CLI --absolute with a stale baseline fails loudly (exit 2)."""
    small_path = tmp_path / "small.json"
    small_path.write_text(json.dumps(make_report(
        "text-embedding-3-small", 1536, _THREE_DIMS)))
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(make_mock_baseline(
        {"Fact Recall": 0.133, "Temporal Updates": 0.700})))
    out = tmp_path / "out.md"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_to_markdown.py",
            "--absolute",
            "--small", str(small_path),
            "--baseline", str(baseline_path),
            "--output", str(out),
        ],
    )

    assert benchmark_to_markdown.main() == 2
    assert "ERROR:" in capsys.readouterr().err


def test_main_single_mode_backward_compatible(tmp_path, monkeypatch):
    """The original positional invocation keeps working (CI uses it)."""
    src = tmp_path / "report.json"
    src.write_text(
        json.dumps(make_report("text-embedding-3-small", 1536, {"Fact Recall": 0.8}))
    )
    out = tmp_path / "out.md"

    monkeypatch.setattr(
        sys, "argv", ["benchmark_to_markdown.py", str(src), str(out)]
    )

    assert benchmark_to_markdown.main() == 0
    assert "# Emerald Benchmark Report" in out.read_text()
