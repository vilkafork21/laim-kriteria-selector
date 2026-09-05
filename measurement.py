"""Определение измерения, подтверждение подключения и идентичность результатов."""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation

VERSION = "laim-monitoring-metric.v3"
POLICY_FIELDS = ("umr_version", "score_column", "basket_id", "solution_version", "name", "assessment_mode", "scoring", "aggregation",
                 "baseline", "primary_validation", "evaluation", "artifact_hashes")
EVIDENCE_TYPES = {"history", "knowledge_context", "tool_results", "customer_context"}


class MeasurementError(ValueError):
    """Определение измерения или его подтверждение не согласованы."""


_ASSESSMENT_MODES = {"qa", "turn_with_history", "dialogue"}
_METHOD_ROLES = {
    "identity": {"final_score": (1, 1)},
    "accuracy": {"prediction": (1, 1), "target": (1, 1)},
    "mean_criteria": {"criterion": (1, None)},
    "all_criteria": {"criterion": (1, None)},
    "majority": {"assessor_vote": (1, None)},
    "all_assessors": {"assessor_vote": (2, None)},
}
_MISSING = {"fail", "exclude_unit", "exclude_value", "zero"}

def _require(mapping: dict, name: str, expected=None):
    if name not in mapping:
        raise MeasurementError(f"monitoring_metric не содержит {name}")
    value = mapping[name]
    if expected is not None and value not in tuple(expected):
        raise MeasurementError(f"Недопустимое {name}: {value!r}")
    return value


def _decimal(value: object, name: str = "value") -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MeasurementError(f"{name} не является Decimal: {value!r}") from exc
    if not result.is_finite():
        raise MeasurementError(f"{name} должно быть конечным")
    return result


def _validate_execution(contract: dict) -> None:
    _require(contract, "basket_id")
    _require(contract, "name")
    if _require(contract, "score_column") != "main_metric":
        raise MeasurementError("Единственная каноническая score-колонка: main_metric")
    _require(contract, "assessment_mode", _ASSESSMENT_MODES)

    scoring = _require(contract, "scoring")
    if not isinstance(scoring, dict):
        raise MeasurementError("scoring должен быть object")
    method = _require(scoring, "method", set(_METHOD_ROLES))
    sources = _require(scoring, "sources")
    if not isinstance(sources, list) or not sources:
        raise MeasurementError("scoring.sources должен быть непустым списком")
    source_ids = set()
    columns = set()
    role_counts: dict[str, int] = {}
    for source in sources:
        if not isinstance(source, dict):
            raise MeasurementError("Каждый scoring source должен быть object")
        for field in ("source_id", "column_name", "role"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                raise MeasurementError(f"scoring.sources.{field} должен быть непустой строкой")
        source_id = _require(source, "source_id")
        if source_id in source_ids:
            raise MeasurementError(f"Повторяется source_id: {source_id}")
        source_ids.add(source_id)
        column = _require(source, "column_name")
        if column in columns:
            raise MeasurementError(f"Повторяется scoring column_name: {column!r}")
        columns.add(column)
        role = _require(source, "role")
        role_counts[role] = role_counts.get(role, 0) + 1
        normalization = _require(source, "normalization")
        if not isinstance(normalization, dict) and normalization not in {"numeric", "label"}:
            raise MeasurementError(f"Недопустимая normalization у {source_id}")
        _require(source, "polarity", {"direct", "inverted"})
    expected_roles = _METHOD_ROLES[method]
    if set(role_counts) != set(expected_roles):
        raise MeasurementError(
            f"Метод {method} требует роли {sorted(expected_roles)}, получено {sorted(role_counts)}"
        )
    for role, (minimum, maximum) in expected_roles.items():
        count = role_counts[role]
        if count < minimum or (maximum is not None and count > maximum):
            raise MeasurementError(f"Недопустимое число источников роли {role}: {count}")
    _require(scoring, "missing_policy", _MISSING)
    denominator = scoring.get("majority_denominator")
    if method == "majority" and denominator not in {"declared", "present"}:
        raise MeasurementError("majority требует denominator declared или present")
    if method != "majority" and denominator is not None:
        raise MeasurementError("majority_denominator допустим только для majority")
    aggregation = _require(contract, "aggregation")
    reducer = _require(aggregation, "method", {"mean", "frequency_weighted_mean"})
    weight_column = aggregation.get("weight_column")
    if reducer == "frequency_weighted_mean" and weight_column != "input_query_count":
        raise MeasurementError("Weighted mean требует input_query_count")
    if reducer == "mean" and weight_column is not None:
        raise MeasurementError("mean не должен объявлять weight_column")

    baseline = _require(contract, "baseline")
    _decimal(_require(baseline, "value"), "baseline.value")
    _decimal(_require(baseline, "recomputed_value"), "baseline.recomputed_value")
    _require(baseline, "scale", {"ratio", "raw"})
    validation = _require(contract, "primary_validation")
    if validation.get("affects_monitoring") is not False:
        raise MeasurementError("Primary validation threshold не должен влиять на monitoring")


def definition_id(metric: dict) -> str:
    policy = {name: value for name, value in metric.items()
              if name not in {"definition_id", "review", "status", "reason", "reason_code"}}
    encoded = json.dumps(policy, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_policy(metric: dict) -> None:
    missing = [name for name in POLICY_FIELDS if name not in metric]
    if missing:
        raise MeasurementError(f"Определение не содержит поля: {missing}")
    for field in ("basket_id", "solution_version", "name"):
        if not isinstance(metric[field], str) or not metric[field].strip():
            raise MeasurementError(f"{field} должен быть непустой строкой")
    if metric["umr_version"] != "laim-umr.v2" or metric["score_column"] != "main_metric":
        raise MeasurementError("Требуются umr_version=laim-umr.v2 и score_column=main_metric")
    for field in ("baseline", "scoring", "aggregation", "primary_validation"):
        if not isinstance(metric[field], dict):
            raise MeasurementError(f"{field} должен быть объектом")
    if metric["baseline"].get("scale") not in ("ratio", "raw"):
        raise MeasurementError("baseline.scale должен быть ratio или raw")
    for field in ("value", "recomputed_value"):
        value = metric["baseline"].get(field)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise MeasurementError(f"baseline.{field} должен быть конечным числом")
    if not isinstance(metric["scoring"].get("method"), str):
        raise MeasurementError("scoring.method должен быть строкой")
    if metric["assessment_mode"] not in ("qa", "turn_with_history", "dialogue"):
        raise MeasurementError(f"Неизвестная единица оценки: {metric['assessment_mode']!r}")
    _validate_execution(metric)
    evaluation = metric["evaluation"]
    if not isinstance(evaluation, dict):
        raise MeasurementError("evaluation должен быть объектом")
    required = {"rubric", "score_values", "higher_is_better", "defect_threshold",
                "required_evidence", "prediction_observable", "observation_profile"}
    if not required <= evaluation.keys():
        raise MeasurementError(f"evaluation не содержит: {sorted(required - evaluation.keys())}")
    values = evaluation["score_values"]
    if (not isinstance(values, list) or len(values) < 2
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
            or sorted(set(values)) != values):
        raise MeasurementError("evaluation.score_values: нужны разные конечные числа по возрастанию")
    if metric["baseline"]["scale"] == "ratio" and (values[0] < 0 or values[-1] > 1):
        raise MeasurementError("Шкала ratio требует score_values внутри [0, 1]")
    threshold = evaluation["defect_threshold"]
    if type(threshold) not in (int, float) or not values[0] <= threshold <= values[-1]:
        raise MeasurementError(f"evaluation.defect_threshold вне шкалы: {threshold!r}")
    if type(evaluation["higher_is_better"]) is not bool:
        raise MeasurementError("evaluation.higher_is_better должен быть bool")
    if not isinstance(evaluation["rubric"], str) or not evaluation["rubric"].strip():
        raise MeasurementError("evaluation.rubric: нужна проверенная инструкция итоговой оценки")
    evidence = evaluation["required_evidence"]
    if (not isinstance(evidence, list) or any(not isinstance(v, str) for v in evidence)
            or len(set(evidence)) != len(evidence) or set(evidence) - EVIDENCE_TYPES):
        raise MeasurementError(f"Неизвестные или повторные required_evidence: {evidence!r}")
    if metric["assessment_mode"] == "turn_with_history" and "history" not in evidence:
        raise MeasurementError("turn_with_history требует явную полноту history")
    observable = evaluation["prediction_observable"]
    if observable not in (None, "route_label", "output_answer"):
        raise MeasurementError(f"Неизвестный prediction_observable: {observable!r}")
    if metric["scoring"]["method"] == "accuracy" and observable is None:
        raise MeasurementError("Accuracy требует явный prediction_observable")
    if evaluation.get("observation_profile") == "fipa_external_reply_v1":
        party = evaluation.get("external_party")
        if not isinstance(party, str) or not party.strip():
            raise MeasurementError("FIPA требует evaluation.external_party из протокола агента")
    profile = evaluation["observation_profile"]
    if profile not in ("fipa_external_reply_v1", "aef_boundary_v1", "state_single_request_v1"):
        raise MeasurementError(f"Неподдерживаемый observation_profile: {profile!r}")
    hashes = metric["artifact_hashes"]
    if not isinstance(hashes, dict) or not hashes:
        raise MeasurementError("artifact_hashes: нужны SHA-256 исходных артефактов")
    if any(not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v)
           for v in hashes.values()):
        raise MeasurementError("artifact_hashes содержит некорректный SHA-256")
    try:
        identifier = definition_id(metric)
    except (TypeError, ValueError) as exc:
        raise MeasurementError("Определение должно содержать только конечные JSON значения") from exc
    if metric.get("definition_id") != identifier:
        raise MeasurementError("definition_id не соответствует содержимому определения")


def validate_review(metric: dict, review: object) -> None:
    if not isinstance(review, dict) or review.get("decision") != "approved":
        raise MeasurementError("Определение измерения не подтверждено при подключении")
    if review.get("definition_id") != metric["definition_id"]:
        raise MeasurementError("Подтверждение относится к другому definition_id")
    if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
        raise MeasurementError("Подтверждение не содержит reviewer")
    try:
        timestamp = datetime.fromisoformat(review["approved_at"])
        if timestamp.tzinfo is None:
            raise ValueError("нет часового пояса")
    except (KeyError, TypeError, ValueError) as exc:
        raise MeasurementError("approved_at требует ISO datetime с часовым поясом") from exc


def validate_measurement(metric: object, *, require_computed: bool = True) -> dict:
    if not isinstance(metric, dict) or metric.get("contract_version") != VERSION:
        raise MeasurementError(f"Ожидается {VERSION}; старое определение требует нового подключения")
    result = deepcopy(metric)
    if result.get("status") == "not_computable":
        if not isinstance(result.get("reason_code"), str) or not result["reason_code"].strip():
            raise MeasurementError("not_computable требует reason_code")
        if require_computed:
            raise MeasurementError(f"Измерение недоступно: {result.get('reason_code')}")
        return result
    if result.get("status") != "computed":
        raise MeasurementError(f"Неизвестный status: {result.get('status')!r}")
    validate_policy(result)
    validate_review(result, result.get("review"))
    if result["baseline"].get("reconciliation") != "match":
        raise MeasurementError("Нельзя допустить несогласованный baseline")
    return result


def approve_measurement(candidate: dict, review: object) -> dict:
    if not isinstance(candidate, dict) or candidate.get("contract_version") != VERSION:
        raise MeasurementError(f"Ожидается кандидат {VERSION}")
    validate_policy(candidate)
    validate_review(candidate, review)
    result = deepcopy(candidate)
    result["review"] = deepcopy(review)
    if result["baseline"].get("reconciliation") != "match":
        result.update(status="not_computable", reason_code="baseline_mismatch",
                      reason="Официальный baseline не согласован с первичной корзиной")
    else:
        result.update(status="computed")
        result.pop("reason", None)
        result.pop("reason_code", None)
    return result
