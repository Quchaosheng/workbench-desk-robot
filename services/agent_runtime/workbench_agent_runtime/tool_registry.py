"""Tool registry with fail-closed parameter validation.

Every SemanticAction dispatched by the Agent Runtime MUST pass through
ToolRegistry.validate() before execution.  The registry is the single source of
truth for legal parameter shapes; A5 (Policy Validator) reads it to build
its whitelist.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from workbench_contracts import ActionType, SemanticAction

from . import tool_schemas as _schemas

# ---------------------------------------------------------------------------
# public types
# ---------------------------------------------------------------------------

_TARGET_REQUIRED_ACTIONS: frozenset[ActionType] = frozenset({ActionType.GRASP, ActionType.PLACE})


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

    Validation layers, applied in order:

    1. **Existence** — the action_type must be registered.
    2. **Target** — GRASP and PLACE require a non-empty ``target_id``.
    3. **Field set** — parameters must contain every required key and no key
       outside the union of required + optional.
    4. **Type safety** — every parameter value must match its declared type.
       ``bool`` is checked *before* ``int`` so that ``True`` / ``False`` can
       never silently pass an integer slot.
    5. **Semantic constraints** — emotion_state enum, observe attribute
       allow-list.
    """

    def __init__(self, *, load_defaults: bool = True) -> None:
        self._tool_param_schemas: dict[ActionType, Mapping[str, object]] = {}
        if load_defaults:
            for action_type, schema in _schemas.TOOL_SCHEMAS.items():
                self.register(action_type, schema)

    # -- public API ----------------------------------------------------------

    def register(self, action_type: ActionType, schema: Mapping[str, object]) -> None:
        """Register a tool schema.

        Raises ``ValueError`` if *action_type* is not an ``ActionType`` member.
        Rejects duplicate registration of an already-registered type."""
        if not isinstance(action_type, ActionType):
            raise ValueError(f"action_type must be an ActionType enum member, got {type(action_type).__name__!r}")
        if action_type in self._tool_param_schemas:
            raise ValueError(f"ActionType '{action_type.value}' is already registered")
        self._tool_param_schemas[action_type] = _freeze_mapping(schema)

    def get(self, action_type: ActionType) -> Mapping[str, object]:
        """Return the schema for *action_type*.

        Raises ``ValueError`` if *action_type* is not an ``ActionType`` member.
        Raises ``KeyError`` if *action_type* is not registered."""
        if not isinstance(action_type, ActionType):
            raise ValueError(f"action_type must be an ActionType enum member, got {type(action_type).__name__!r}")
        if action_type not in self._tool_param_schemas:
            raise KeyError(action_type)
        return self._tool_param_schemas[action_type]

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

        This method **never raises** — every rejection is encoded in the result
        so callers cannot accidentally skip validation by forgetting a
        ``try`` / ``except``.  Even a non-ActionType input is caught and
        returned as a validation failure rather than an exception.
        """
        errors: list[ValidationError] = []

        # ---- 0. guard — is action_type even an ActionType? ------------------
        try:
            action_type_value = action.action_type.value
        except AttributeError:
            return ValidationResult.fail(
                action.action_id,
                [
                    ValidationError(
                        "action_type",
                        f"expected an ActionType enum member, got {type(action.action_type).__name__!r}",
                    )
                ],
            )

        # ---- 1. existence --------------------------------------------------
        if action.action_type not in self._tool_param_schemas:
            return ValidationResult.fail(
                action.action_id,
                [
                    ValidationError(
                        "action_type",
                        f"unknown action_type '{action_type_value}'; "
                        f"allowed: {sorted(t.value for t in self._tool_param_schemas)}",
                    )
                ],
            )
        schema = self._tool_param_schemas[action.action_type]
        target_id_required: bool = schema.get("target_id_required", False)
        required: frozenset[str] = schema["required_params"]
        optional: frozenset[str] = schema["optional_params"]
        allowed: frozenset[str] = required | optional
        param_types: dict[str, type | object] = schema["param_types"]
        params: dict[str, object] = action.parameters or {}

        # ---- 2. target_id ---------------------------------------------------
        if target_id_required:
            if not isinstance(action.target_id, str) or not action.target_id.strip():
                errors.append(
                    ValidationError(
                        "target_id",
                        f"'{action_type_value}' requires a non-empty target_id",
                    )
                )

        # ---- 3. field set --------------------------------------------------
        actual_keys = set(params)
        extra = actual_keys - allowed
        missing = required - actual_keys

        if extra:
            errors.append(
                ValidationError(
                    "parameters",
                    f"forbidden keys for '{action_type_value}': " f"{sorted(extra)}; allowed: {sorted(allowed)}",
                )
            )
        if missing:
            errors.append(
                ValidationError(
                    "parameters",
                    f"missing required keys for '{action_type_value}': " f"{sorted(missing)}",
                )
            )
        # early-exit when the field set is broken — type checking on a
        # structurally invalid dict produces noisy secondary errors.
        if errors:
            return ValidationResult.fail(action.action_id, errors)

        # ---- 4. type safety ------------------------------------------------
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

        # ---- 5. semantic constraints ----------------------------------------
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

        if action.action_type is ActionType.OBSERVE:
            raw_attributes = params.get("attributes")
            if isinstance(raw_attributes, list):
                unknown_attrs = [
                    attr
                    for attr in raw_attributes
                    if not isinstance(attr, str) or attr not in _schemas.KNOWN_OBSERVE_ATTRIBUTES
                ]
                if unknown_attrs:
                    errors.append(
                        ValidationError(
                            "parameters.attributes",
                            f"unknown observe attributes: {unknown_attrs}; "
                            f"allowed: {sorted(_schemas.KNOWN_OBSERVE_ATTRIBUTES)}",
                        )
                    )
                # Each element must be a string
                non_strings = [attr for attr in raw_attributes if not isinstance(attr, str)]
                if non_strings:
                    errors.append(
                        ValidationError(
                            "parameters.attributes",
                            f"all observe attributes must be strings, got: " f"{[_type_label(a) for a in non_strings]}",
                        )
                    )

        if errors:
            return ValidationResult.fail(action.action_id, errors)
        return ValidationResult.ok(action.action_id)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _type_label(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    return type(value).__name__


def _freeze_mapping(value: Mapping[object, object]) -> Mapping:
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze_value(item) for item in value)
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    return value


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
