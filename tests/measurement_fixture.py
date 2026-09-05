"""Синтетическое подтверждённое определение для тестов; в runtime не импортируется."""
from measurement import VERSION, approve_measurement, definition_id


def reviewed_metric(metric, **evaluation):
    metric["contract_version"] = VERSION
    metric.setdefault("umr_version", "laim-umr.v2")
    metric.setdefault("basket_id", "CI09000001")
    metric.setdefault("solution_version", "test-v1")
    metric.setdefault("name", "Тестовая КМ")
    metric.setdefault("score_column", "main_metric")
    metric.setdefault("primary_validation", {"affects_monitoring": False})
    metric.setdefault("aggregation", {"method": "mean", "weight_column": None})
    metric["scoring"].setdefault("missing_policy", "exclude_unit")
    metric["scoring"].setdefault("majority_denominator", None)
    for source in metric["scoring"]["sources"]:
        source.setdefault("polarity", "direct")
        source.setdefault("normalization", "label" if source["role"] in ("prediction", "target") else "numeric")
    baseline = metric.setdefault("baseline", {"value": 0.5, "recomputed_value": 0.5, "scale": "ratio"})
    baseline.setdefault("reconciliation", "match")
    metric["artifact_hashes"] = {"synthetic": "0" * 64}
    metric["evaluation"] = {
        "rubric": "1 — корректный ответ по инструкции, 0 — некорректный",
        "score_values": [0, 1], "higher_is_better": True, "defect_threshold": 1,
        "required_evidence": ["history"] if metric["assessment_mode"] == "turn_with_history" else [],
        "prediction_observable": "route_label" if metric["scoring"]["method"] == "accuracy" else None,
        "observation_profile": "aef_boundary_v1", **evaluation,
    }
    metric["definition_id"] = definition_id(metric)
    return approve_measurement(metric, {
        "decision": "approved", "definition_id": metric["definition_id"],
        "reviewer": "test-reviewer", "approved_at": "2026-09-05T12:00:00+03:00",
    })
