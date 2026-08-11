"""Tool registry with fail-closed parameter validation.

Every SemanticAction dispatched by the Agent Runtime MUST pass through
ToolRegistry.validate() before execution.  The registry is the single source of
truth for legal parameter shapes; A5 (Policy Validator) reads it to build
its whitelist.
"""

from __future__ import annotations

from dataclasses import dataclass

from workbench_contracts import ActionType, SemanticAction

from . import tool_schemas as _schemas

# ---------------------------------------------------------------------------
# public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationError:
    """A single validation failure."""

    field: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating one SemanticAction against the registry."""

    is_valid: bool
    action_id: str
    errors: tuple[ValidationError, ...] = ()

    def __bool__(self) -> bool:
        return self.is_valid

    @classmethod
    def ok(cls, action_id: str) -> ValidationResult:
        return cls(is_valid=True, action_id=action_id)

    @classmethod
    def fail(cls, action_id: str, errors: list[ValidationError]) -> ValidationResult:
        return cls(is_valid=False, action_id=action_id, errors=tuple(errors))


# ---------------------------------------------------------------------------
# registry implementation
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Register and validate the six bounded semantic-action tools.

    Three layers of validation, applied in order:

    1. **Existence** — the action_type must be registered.
    2. **Field set** — parameters must contain every required key and no key
       outside the union of required + optional.
    3. **Type safety** — every parameter value must match its declared type.
       ``bool`` is checked *before* ``int`` so that ``True`` / ``False`` can
       never silently pass an integer slot.
    """

    def __init__(self) -> None:
        self._tool_param_schemas: dict[ActionType, dict[str, object]] = {}
        for action_type, schema in _schemas.TOOL_SCHEMAS.items():
            self._tool_param_schemas[action_type] = schema

    # -- public API ----------------------------------------------------------

    def list_all(self) -> tuple[ActionType, ...]:
        """Return every registered ActionType."""
        return tuple(self._tool_param_schemas)

    def required_params(self, action_type: ActionType) -> frozenset[str]:
        return self._tool_param_schemas[action_type]["required_params"]

    def optional_params(self, action_type: ActionType) -> frozenset[str]:
        return self._tool_param_schemas[action_type]["optional_params"]

    def allowed_params(self, action_type: ActionType) -> frozenset[str]:
        schema = self._tool_param_schemas[action_type]
        return schema["required_params"] | schema["optional_params"]

    def validate(self, action: SemanticAction) -> ValidationResult:
        """Validate *action* and return ``ValidationResult``.

        This method never raises — every rejection is encoded in the result
        so callers cannot accidentally skip validation by forgetting a
        ``try`` / ``except``.
        """
        errors: list[ValidationError] = []

        # ---- 1. existence --------------------------------------------------
        if action.action_type not in self._tool_param_schemas:
            return ValidationResult.fail(
                action.action_id,
                [
                    ValidationError(
                        "action_type",
                        f"unknown action_type '{action.action_type.value}'; "
                        f"allowed: {sorted(t.value for t in self._tool_param_schemas)}",
                    )
                ],
            )
        schema = self._tool_param_schemas[action.action_type]
        required: frozenset[str] = schema["required_params"]
        optional: frozenset[str] = schema["optional_params"]
        allowed: frozenset[str] = required | optional
        param_types: dict[str, type | object] = schema["param_types"]
        params: dict[str, object] = action.parameters or {}

        # ---- 2. field set --------------------------------------------------
        actual_keys = set(params)
        extra = actual_keys - allowed
        missing = required - actual_keys

        if extra:
            errors.append(
                ValidationError(
                    "parameters",
                    f"forbidden keys for '{action.action_type.value}': " f"{sorted(extra)}; allowed: {sorted(allowed)}",
                )
            )
        if missing:
            errors.append(
                ValidationError(
                    "parameters",
                    f"missing required keys for '{action.action_type.value}': " f"{sorted(missing)}",
                )
            )
        # early-exit when the field set is broken — type checking on a
        # structurally invalid dict produces noisy secondary errors.
        if errors:
            return ValidationResult.fail(action.action_id, errors)

        # ---- 3. type safety ------------------------------------------------
        for key, value in params.items():
            expected_type = param_types.get(key)
            if expected_type is None:
                # param has no declared type — permissive
                continue

            if expected_type is bool:
                if not isinstance(value, bool):
                    errors.append(
                        ValidationError(
                            f"parameters.{key}",
                            f"expected bool, got {_type_label(value)}",
                        )
                    )
                continue

            if expected_type is int:
                # bool is a subclass of int in Python — reject it explicitly
                if isinstance(value, bool):
                    errors.append(
                        ValidationError(
                            f"parameters.{key}",
                            "expected int, got bool (bool is not int)",
                        )
                    )
                elif not isinstance(value, int):
                    errors.append(
                        ValidationError(
                            f"parameters.{key}",
                            f"expected int, got {_type_label(value)}",
                        )
                    )
                continue

            if expected_type is float:
                if isinstance(value, bool):
                    errors.append(
                        ValidationError(
                            f"parameters.{key}",
                            "expected float, got bool",
                        )
                    )
                elif not isinstance(value, int | float):
                    errors.append(
                        ValidationError(
                            f"parameters.{key}",
                            f"expected float, got {_type_label(value)}",
                        )
                    )
                continue

            if expected_type is str:
                if not isinstance(value, str):
                    errors.append(
                        ValidationError(
                            f"parameters.{key}",
                            f"expected str, got {_type_label(value)}",
                        )
                    )
                continue

            if expected_type is list:
                if not isinstance(value, list):
                    errors.append(
                        ValidationError(
                            f"parameters.{key}",
                            f"expected list, got {_type_label(value)}",
                        )
                    )
                continue

            # generic isinstance fallback
            if not isinstance(value, expected_type):
                errors.append(
                    ValidationError(
                        f"parameters.{key}",
                        f"expected {_type_name(expected_type)}, " f"got {_type_label(value)}",
                    )
                )

        # ---- 4. semantic constraints ----------------------------------------
        if action.action_type is ActionType.EXPRESS:
            emotion = params.get("emotion_state")
            if isinstance(emotion, str) and emotion not in _schemas.EXPRESS_EMOTION_STATES:
                errors.append(
                    ValidationError(
                        "parameters.emotion_state",
                        f"'{emotion}' is not a valid emotion state; "
                        f"allowed: {sorted(_schemas.EXPRESS_EMOTION_STATES)}",
                    )
                )

        if errors:
            return ValidationResult.fail(action.action_id, errors)
        return ValidationResult.ok(action.action_id)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _type_label(value: object) -> str:
    typename = type(value).__name__
    if isinstance(value, bool):
        return "bool"
    return typename


def _type_name(tp: type | object) -> str:
    if tp is str:
        return "str"
    if tp is int:
        return "int"
    if tp is float:
        return "float"
    if tp is bool:
        return "bool"
    if tp is list:
        return "list"
    return getattr(tp, "__name__", str(tp))
