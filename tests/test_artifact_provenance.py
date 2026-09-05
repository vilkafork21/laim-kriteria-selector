"""Допуск определения вместо повторного выбора КМ из отчётов."""
# ruff: noqa: E402
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from measurement import MeasurementError, definition_id
from measurement_fixture import reviewed_metric

spec = importlib.util.spec_from_file_location("selector", ROOT / "main.py")
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


def candidate():
    metric = reviewed_metric({
        "assessment_mode": "qa", "scoring": {"method": "identity", "sources": [
            {"source_id": "source_1", "column_name": "main_metric", "role": "final_score",
             "normalization": "numeric", "polarity": "direct"}],
            "missing_policy": "exclude_unit", "majority_denominator": None},
        "aggregation": {"method": "mean", "weight_column": None},
    })
    review = metric.pop("review")
    metric.update(status="not_computable", reason_code="measurement_review_required")
    return metric, review


def publish(metric, review=None):
    return selector.main(metric, {"agent_ci": "CI09000001", "solution_version": "test-v1"}, review)["validated_monitoring_metric"]


def test_candidate_is_unavailable_until_reviewed():
    metric, _ = candidate()
    assert publish(metric)["status"] == "not_computable"


def test_review_publishes_exact_definition_without_mutation():
    metric, review = candidate()
    original = deepcopy(metric)
    result = publish(metric, review)
    assert result["status"] == "computed"
    assert result["definition_id"] == definition_id(result)
    assert metric == original
    assert result["review"] == review


@pytest.mark.parametrize("field,value", [
    ("rubric", "Другая инструкция"), ("score_values", [0, 0.5, 1]),
    ("higher_is_better", False), ("defect_threshold", 0),
    ("required_evidence", ["customer_context"]),
    ("prediction_observable", "output_answer"),
    ("observation_profile", "state_single_request_v1"),
])
def test_review_cannot_be_reused_after_semantic_change(field, value):
    metric, review = candidate()
    metric["evaluation"][field] = value
    with pytest.raises(MeasurementError, match="definition_id"):
        publish(metric, review)
    metric["definition_id"] = definition_id(metric)
    with pytest.raises(MeasurementError, match="другому definition_id"):
        publish(metric, review)


def test_changed_artifact_requires_new_review():
    metric, review = candidate()
    metric["artifact_hashes"]["synthetic"] = "1" * 64
    with pytest.raises(MeasurementError, match="definition_id"):
        publish(metric, review)


def test_other_agent_is_rejected():
    metric, review = candidate()
    with pytest.raises(MeasurementError, match="другому агенту"):
        selector.main(metric, {"agent_ci": "CI09000002"}, review)


@pytest.mark.parametrize("field,value", [("reviewer", ""), ("decision", "pending"),
                                         ("approved_at", "2026-09-05")])
def test_incomplete_review_is_rejected(field, value):
    metric, review = candidate()
    review[field] = value
    with pytest.raises(MeasurementError):
        publish(metric, review)


def test_human_approval_cannot_override_baseline_mismatch():
    metric, review = candidate()
    metric["baseline"].update(reconciliation="mismatch", recomputed_value=0.9)
    metric["definition_id"] = definition_id(metric)
    review["definition_id"] = metric["definition_id"]
    result = publish(metric, review)
    assert result["status"] == "not_computable"
    assert result["reason_code"] == "baseline_mismatch"
    assert result["baseline"]["value"] == 0.5


@pytest.mark.parametrize("version", ["laim-monitoring-metric.v1", "laim-monitoring-metric.v2"])
def test_old_contract_is_not_implicitly_approved(version):
    metric, review = candidate()
    metric["contract_version"] = version
    with pytest.raises(MeasurementError, match="v3"):
        publish(metric, review)


def test_failed_compilation_cannot_be_approved():
    metric, review = candidate()
    metric.pop("definition_id")
    assert publish(metric)["status"] == "not_computable"
    with pytest.raises(MeasurementError, match="непостроенное"):
        publish(metric, review)
    metric["status"] = "computed"
    with pytest.raises(MeasurementError, match="definition_id"):
        publish(metric)


@pytest.mark.parametrize("field", ["baseline", "scoring", "aggregation", "evaluation"])
def test_malformed_policy_has_domain_error(field):
    metric, review = candidate()
    metric[field] = None
    with pytest.raises(MeasurementError, match=field):
        publish(metric, review)


def test_deployment_has_only_onboarding_ports_and_local_sources():
    descriptor = json.loads((ROOT / "descriptor.json").read_text())
    assert {p["name"] for p in descriptor["ports"]} == {
        "monitoring_metric", "measurement_review", "run_context", "validated_monitoring_metric"}
    assert set(descriptor["script"]["runConfiguration"]["sourceFiles"]) == {"main.py", "measurement.py"}
    assert not (ROOT / "requirements.txt").read_text().strip()


def test_another_solution_version_cannot_reuse_review():
    metric, review = candidate()
    with pytest.raises(MeasurementError, match="solution_version"):
        selector.main(metric, {"agent_ci": "CI09000001", "solution_version": "test-v2"}, review)


@pytest.mark.parametrize("field,value", [("scoring", {"method": "invented"}),
                                         ("aggregation", {}), ("primary_validation", {})])
def test_review_does_not_approve_an_unexecutable_definition(field, value):
    metric, review = candidate()
    metric[field] = value
    metric["definition_id"] = definition_id(metric)
    review["definition_id"] = metric["definition_id"]
    with pytest.raises(MeasurementError):
        publish(metric, review)
