from typing import Any

from app.schemas import PayloadCondition, SubscriberFilters


def get_nested_value(payload: dict[str, Any], field_path: str) -> Any:
    current: Any = payload
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def payload_condition_matches(condition: PayloadCondition, payload: dict[str, Any]) -> bool:
    value = get_nested_value(payload, condition.field)

    if condition.operator == "exists":
        return value is not None

    if condition.operator == "eq":
        return value == condition.value

    if condition.operator == "neq":
        return value != condition.value

    if condition.operator == "contains":
        if isinstance(value, str) and isinstance(condition.value, str):
            return condition.value in value
        if isinstance(value, (list, tuple, set)):
            return condition.value in value
        return False

    return False


def filters_match(
    filters: SubscriberFilters,
    *,
    event_type: str,
    source: str,
    payload: dict[str, Any],
) -> bool:
    if filters.type is not None and filters.type != event_type:
        return False

    if filters.source is not None and filters.source != source:
        return False

    return all(
        payload_condition_matches(condition, payload)
        for condition in filters.payload_conditions
    )
