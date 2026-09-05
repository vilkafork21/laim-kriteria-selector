"""Публикация определения измерения после проверки при подключении агента."""
from __future__ import annotations

import logging
from copy import deepcopy

from measurement import MeasurementError, approve_measurement, validate_policy, VERSION

logger = logging.getLogger(__name__)


def main(monitoring_metric: dict, run_context: dict,
         measurement_review: dict | None = None) -> dict[str, object]:
    if not isinstance(monitoring_metric, dict) or monitoring_metric.get("contract_version") != VERSION:
        raise MeasurementError(f"Ожидается monitoring_metric {VERSION}")
    agent = run_context.get("agent_ci") if isinstance(run_context, dict) else None
    if not isinstance(agent, str) or agent.strip().upper() != monitoring_metric.get("basket_id"):
        raise MeasurementError(f"Определение относится к другому агенту: agent_ci={agent!r}")
    version = run_context.get("solution_version")
    if (monitoring_metric.get("definition_id")
            and (not isinstance(version, str) or version != monitoring_metric.get("solution_version"))):
        raise MeasurementError(f"Определение относится к другой solution_version: {version!r}")
    result = deepcopy(monitoring_metric)
    if "definition_id" not in result:
        if result.get("status") != "not_computable" or not result.get("reason_code"):
            raise MeasurementError("Кандидат без definition_id требует причины недоступности")
        if measurement_review is not None:
            raise MeasurementError("Нельзя подтвердить непостроенное определение")
        logger.warning("Кандидат определения не построен: %s", result.get("reason_code"))
    else:
        validate_policy(result)
        if measurement_review is None:
            result.update(status="not_computable", reason_code="measurement_review_required",
                          reason="Нет подтверждения определения измерения при подключении")
            logger.warning(result["reason"])
        else:
            result = approve_measurement(result, measurement_review)
            logger.info("Определение %s: %s", result["definition_id"], result["status"])
    return {"validated_monitoring_metric": result}
