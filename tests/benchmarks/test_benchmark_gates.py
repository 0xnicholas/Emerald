"""Dual-gate evaluation (issue #19, T3) — deterministic unit tests.

Covers the pure function `evaluate_gates` (pass / fail / missing
dimension / exact-boundary scores) and the mock-baseline loader
(missing file / invalid JSON / valid report).
"""

import json

import pytest

from scripts.benchmark_gates import (
    DEFAULT_MOCK_BASELINE_PATH,
    GateEvaluationError,
    evaluate_gates,
    load_mock_baseline,
)

# The 7 canonical dimensions (post-T1).
DIMENSIONS = [
    "Fact Recall",
    "Temporal Updates",
    "Relationship Classification",
    "Profile Accuracy",
    "Distractor Resistance",
    "Forgetting Correctness",
    "Contradiction Chain",
]

CC = "Contradiction Chain"


def _report(scores: dict[str, float]) -> dict:
    """Synthetic report: each dimension carries one pickable key metric."""
    return {
        "results": [
            {"name": name, "metrics": {"overall_accuracy": score}} for name, score in scores.items()
        ]
    }


def _baseline(scores: dict[str, float]) -> dict:
    return _report(scores)


def _all_dims(score: float, cc: float | None = None) -> dict[str, float]:
    scores = {name: score for name in DIMENSIONS}
    if cc is not None:
        scores[CC] = cc
    return scores


class TestEvaluateGates:
    def test_both_gates_pass(self):
        report = _report(_all_dims(0.75, cc=0.9))
        baseline = _baseline(_all_dims(0.5))

        result = evaluate_gates(report, baseline)

        assert result.release_passed is True
        assert result.pass_gate_passed is True
        assert result.contradiction_chain_score == 0.9
        assert result.average_score == pytest.approx((6 * 0.75 + 0.9) / 7)
        assert len(result.dimensions) == 7
        assert all(d.passed for d in result.dimensions)
        assert result.to_dict()["release_gate"]["passed"] is True
        assert result.to_dict()["pass_gate"]["passed"] is True

    def test_release_gate_fails_when_one_dimension_below_baseline(self):
        report = _report(_all_dims(0.75, cc=0.9))
        baseline = _baseline({**{d: 0.5 for d in DIMENSIONS}, CC: 0.95})

        result = evaluate_gates(report, baseline)

        assert result.release_passed is False
        cc_comp = next(d for d in result.dimensions if d.name == CC)
        assert cc_comp.passed is False
        assert cc_comp.score == 0.9
        assert cc_comp.baseline == 0.95
        # Other dimensions still pass individually
        assert sum(1 for d in result.dimensions if d.passed) == 6
        # Pass gate is independent of the release gate
        assert result.pass_gate_passed is True

    def test_release_gate_boundary_exact_equal_passes(self):
        """score == baseline counts as passing (>= semantics)."""
        report = _report(_all_dims(0.5))
        baseline = _baseline(_all_dims(0.5))

        result = evaluate_gates(report, baseline)

        assert result.release_passed is True
        assert all(d.passed for d in result.dimensions)

    def test_pass_gate_fails_when_cc_below_threshold(self):
        report = _report(_all_dims(0.75, cc=0.79))
        baseline = _baseline(_all_dims(0.5))

        result = evaluate_gates(report, baseline)

        assert result.release_passed is True
        assert result.pass_gate_passed is False
        assert result.contradiction_chain_score == 0.79

    def test_pass_gate_cc_boundary_exactly_80_passes(self):
        """CC exactly 0.80 satisfies the >= 0.80 threshold."""
        report = _report(_all_dims(0.75, cc=0.8))
        baseline = _baseline(_all_dims(0.5))

        result = evaluate_gates(report, baseline)

        assert result.pass_gate_passed is True

    def test_pass_gate_avg_boundary_exactly_70_passes(self):
        """Average exactly 0.70 satisfies the >= 0.70 threshold."""
        # 1.0 + 6 × 0.65 → average 0.7000000000000001 (>= 0.7)
        report = _report({**{d: 0.65 for d in DIMENSIONS}, CC: 1.0})
        baseline = _baseline(_all_dims(0.5))

        result = evaluate_gates(report, baseline)

        assert result.average_score == pytest.approx(0.7, abs=1e-9)
        assert result.pass_gate_passed is True

    def test_pass_gate_fails_when_avg_below_70(self):
        # 1.0 + 6 × 0.649 → average 0.69914... (< 0.7)
        report = _report({**{d: 0.649 for d in DIMENSIONS}, CC: 1.0})
        baseline = _baseline(_all_dims(0.5))

        result = evaluate_gates(report, baseline)

        assert result.pass_gate_passed is False

    def test_missing_dimension_in_report_raises(self):
        report = _report(_all_dims(0.75))
        del report["results"][0]  # drop "Fact Recall"
        baseline = _baseline(_all_dims(0.5))

        with pytest.raises(GateEvaluationError, match="Fact Recall"):
            evaluate_gates(report, baseline)

    def test_missing_dimension_in_baseline_raises(self):
        report = _report(_all_dims(0.75))
        baseline = _baseline(_all_dims(0.5))
        del baseline["results"][0]

        with pytest.raises(GateEvaluationError, match="Fact Recall"):
            evaluate_gates(report, baseline)

    def test_missing_results_list_raises(self):
        with pytest.raises(GateEvaluationError, match="results"):
            evaluate_gates({"config": {}}, _baseline(_all_dims(0.5)))
        with pytest.raises(GateEvaluationError, match="results"):
            evaluate_gates(_report(_all_dims(0.75)), {"config": {}})

    def test_pass_gate_missing_cc_raises(self):
        """Pass gate needs the Contradiction Chain dimension (blocked-by #17)."""
        scores = {name: 0.75 for name in DIMENSIONS if name != CC}
        report = _report(scores)
        baseline = _baseline(scores)

        with pytest.raises(GateEvaluationError, match=CC):
            evaluate_gates(report, baseline)

    def test_dimension_without_pickable_metric_raises(self):
        report = _report(_all_dims(0.75))
        report["results"][0] = {
            "name": "Fact Recall",
            "metrics": {"total_facts": 100},  # no key metric
        }

        with pytest.raises(GateEvaluationError, match="Fact Recall"):
            evaluate_gates(report, _baseline(_all_dims(0.5)))

    def test_non_dict_result_entry_raises(self):
        report = _report(_all_dims(0.75))
        report["results"][0] = None

        with pytest.raises(GateEvaluationError, match="不是对象"):
            evaluate_gates(report, _baseline(_all_dims(0.5)))

    def test_null_metrics_raises(self):
        report = _report(_all_dims(0.75))
        report["results"][0] = {"name": "Fact Recall", "metrics": None}

        with pytest.raises(GateEvaluationError, match="metrics"):
            evaluate_gates(report, _baseline(_all_dims(0.5)))

    def test_duplicate_dimension_name_raises(self):
        report = _report(_all_dims(0.75))
        report["results"].append(dict(report["results"][0]))  # duplicate name

        with pytest.raises(GateEvaluationError, match="重复"):
            evaluate_gates(report, _baseline(_all_dims(0.5)))

    def test_divergent_picked_metric_keys_raise(self):
        """Same dimension but different picked key metric on each side is
        an apples-to-oranges comparison and must fail loudly."""
        report = _report(_all_dims(0.75))
        baseline = _baseline(_all_dims(0.5))
        # Baseline's Fact Recall only carries a different key metric
        baseline["results"][0]["metrics"] = {"mrr": 0.5}

        with pytest.raises(GateEvaluationError, match="关键指标不一致"):
            evaluate_gates(report, baseline)


class TestLoadMockBaseline:
    def test_missing_file_raises_clear_error(self):
        with pytest.raises(GateEvaluationError, match="不存在"):
            load_mock_baseline("/nonexistent/mock-baseline.json")

    def test_invalid_json_raises_clear_error(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")

        with pytest.raises(GateEvaluationError, match="JSON"):
            load_mock_baseline(bad)

    def test_missing_results_raises_clear_error(self, tmp_path):
        bad = tmp_path / "no-results.json"
        bad.write_text(json.dumps({"config": {}}), encoding="utf-8")

        with pytest.raises(GateEvaluationError, match="results"):
            load_mock_baseline(bad)

    def test_valid_report_returns_dict(self, tmp_path):
        good = tmp_path / "good.json"
        report = _baseline(_all_dims(0.5))
        good.write_text(json.dumps(report), encoding="utf-8")

        loaded = load_mock_baseline(good)

        assert len(loaded["results"]) == 7

    def test_default_path_points_into_committed_docs(self):
        assert str(DEFAULT_MOCK_BASELINE_PATH).endswith("docs/benchmarks/mock-baseline.json")


class TestCli:
    """CLI exit codes: 0 both gates pass, 1 a gate fails, 2 evaluation error."""

    def _write(self, tmp_path, name: str, payload: dict):
        p = tmp_path / name
        p.write_text(json.dumps(payload), encoding="utf-8")
        return str(p)

    def test_exit_zero_when_both_gates_pass(self, tmp_path, monkeypatch, capsys):
        from scripts.benchmark_gates import main

        report = self._write(tmp_path, "real.json", _report(_all_dims(0.75, cc=0.9)))
        baseline = self._write(tmp_path, "mock.json", _baseline(_all_dims(0.5)))
        monkeypatch.setattr("sys.argv", ["benchmark_gates", report, "--baseline", baseline])

        assert main() == 0
        out = capsys.readouterr().out
        assert "通过" in out

    def test_exit_one_when_gate_fails(self, tmp_path, monkeypatch):
        from scripts.benchmark_gates import main

        report = self._write(tmp_path, "real.json", _report(_all_dims(0.4)))
        baseline = self._write(tmp_path, "mock.json", _baseline(_all_dims(0.5)))
        monkeypatch.setattr("sys.argv", ["benchmark_gates", report, "--baseline", baseline])

        assert main() == 1

    def test_exit_two_when_baseline_missing(self, tmp_path, monkeypatch, capsys):
        from scripts.benchmark_gates import main

        report = self._write(tmp_path, "real.json", _report(_all_dims(0.75)))
        monkeypatch.setattr(
            "sys.argv",
            ["benchmark_gates", report, "--baseline", str(tmp_path / "nope.json")],
        )

        assert main() == 2
        assert "不存在" in capsys.readouterr().err

    def test_json_output_contains_both_gates(self, tmp_path, monkeypatch, capsys):
        from scripts.benchmark_gates import main

        report = self._write(tmp_path, "real.json", _report(_all_dims(0.75, cc=0.9)))
        baseline = self._write(tmp_path, "mock.json", _baseline(_all_dims(0.5)))
        monkeypatch.setattr(
            "sys.argv",
            ["benchmark_gates", report, "--baseline", baseline, "--json"],
        )

        assert main() == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["release_gate"]["passed"] is True
        assert payload["pass_gate"]["passed"] is True
        assert len(payload["release_gate"]["dimensions"]) == 7
