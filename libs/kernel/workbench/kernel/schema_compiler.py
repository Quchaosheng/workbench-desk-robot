"""K1-K2: compile object-shaped JSON Schemas to Python and TypeScript models."""

import json
import keyword
import math
import re
from pathlib import Path
from typing import Any

SCHEMA_SUFFIX = ".schema.json"
ROOT_KEYWORDS = {
    "$schema",
    "title",
    "description",
    "type",
    "required",
    "properties",
    "additionalProperties",
    "allOf",
}
PROPERTY_KEYWORDS = {
    "$ref",
    "description",
    "enum",
    "items",
    "maximum",
    "minimum",
    "minItems",
    "pattern",
    "properties",
    "required",
    "type",
}
RUNTIME_SCHEMA_KEYWORDS = (ROOT_KEYWORDS | PROPERTY_KEYWORDS) - {"$ref"} | {
    "anyOf",
    "const",
    "else",
    "if",
    "not",
    "then",
}


class SchemaValidationError(ValueError):
    """Raised when a value does not satisfy the supported schema subset."""


def _is_finite_json_number(value: Any) -> bool:
    """Return whether value is a JSON number representable by the runtime validator."""
    if type(value) is int:
        return True
    return type(value) is float and math.isfinite(value)


def _numeric_constraint(schema: dict[str, Any], keyword: str, location: str) -> int | float:
    bound = schema[keyword]
    if not _is_finite_json_number(bound):
        raise SchemaValidationError(f"schema {keyword} at {location} must be a finite number")
    return bound


def _matches_json_type(value: Any, schema_type: str) -> bool:
    if schema_type == "null":
        return value is None
    if schema_type == "boolean":
        return type(value) is bool
    if schema_type == "integer":
        return type(value) is int
    if schema_type == "number":
        return _is_finite_json_number(value)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "object":
        return isinstance(value, dict)
    raise SchemaValidationError(f"unsupported schema type {schema_type!r}")


def _enum_contains(enum: list[Any], value: Any) -> bool:
    return any(type(candidate) is type(value) and candidate == value for candidate in enum)


def _schema_matches(
    value: Any,
    schema: dict[str, Any],
    *,
    references: dict[str, dict[str, Any]] | None,
    location: str,
) -> bool:
    try:
        validate_schema_instance(value, schema, references=references, location=location)
    except SchemaValidationError:
        return False
    return True


def validate_schema_instance(
    value: Any,
    schema: dict[str, Any],
    *,
    references: dict[str, dict[str, Any]] | None = None,
    location: str = "$",
) -> None:
    """Validate one value against the JSON Schema subset the compiler supports."""
    if not isinstance(schema, dict):
        raise SchemaValidationError(f"schema at {location} must be an object")
    if type(value) is float and not math.isfinite(value):
        raise SchemaValidationError(f"value at {location} must be a finite JSON number")
    if "$ref" in schema:
        reference = schema["$ref"]
        referenced = (references or {}).get(reference)
        if referenced is None:
            raise SchemaValidationError(f"unresolved schema reference {reference!r} at {location}")
        validate_schema_instance(value, referenced, references=references, location=location)
        return

    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise SchemaValidationError(f"value at {location} does not match const {schema['const']!r}")

    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or not _enum_contains(enum, value):
            raise SchemaValidationError(f"value at {location} is not in the allowed enum")

    schema_types = schema.get("type")
    if schema_types is not None:
        allowed_types = schema_types if isinstance(schema_types, list) else [schema_types]
        if not all(isinstance(schema_type, str) for schema_type in allowed_types):
            raise SchemaValidationError(f"schema type at {location} must be a string or string list")
        if not any(_matches_json_type(value, schema_type) for schema_type in allowed_types):
            raise SchemaValidationError(f"value at {location} does not match type {schema_types!r}")

    if "minimum" in schema:
        minimum = _numeric_constraint(schema, "minimum", location)
        try:
            below_minimum = not _is_finite_json_number(value) or value < minimum
        except (OverflowError, TypeError) as exc:
            raise SchemaValidationError(f"value at {location} cannot be compared with minimum {minimum!r}") from exc
        if below_minimum:
            raise SchemaValidationError(f"value at {location} is below minimum {minimum!r}")
    if "maximum" in schema:
        maximum = _numeric_constraint(schema, "maximum", location)
        try:
            above_maximum = not _is_finite_json_number(value) or value > maximum
        except (OverflowError, TypeError) as exc:
            raise SchemaValidationError(f"value at {location} cannot be compared with maximum {maximum!r}") from exc
        if above_maximum:
            raise SchemaValidationError(f"value at {location} is above maximum {maximum!r}")
    if "pattern" in schema:
        pattern = schema["pattern"]
        if not isinstance(pattern, str):
            raise SchemaValidationError(f"schema pattern at {location} must be a string")
        try:
            matcher = re.compile(pattern)
        except re.error as exc:
            raise SchemaValidationError(f"schema pattern at {location} is invalid") from exc
        if not isinstance(value, str) or matcher.search(value) is None:
            raise SchemaValidationError(f"value at {location} does not match pattern {pattern!r}")
    if "minItems" in schema:
        min_items = schema["minItems"]
        if type(min_items) is not int or min_items < 0:
            raise SchemaValidationError(f"schema minItems at {location} must be a non-negative integer")
        if not isinstance(value, list) or len(value) < min_items:
            raise SchemaValidationError(f"array at {location} has fewer than {min_items} items")

    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            validate_schema_instance(
                item,
                schema["items"],
                references=references,
                location=f"{location}[{index}]",
            )

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise SchemaValidationError(f"object schema at {location} has invalid properties or required fields")
        missing = set(required) - set(value)
        if missing:
            raise SchemaValidationError(f"object at {location} is missing fields: {sorted(missing)}")
        if schema.get("additionalProperties", True) is False:
            extra = set(value) - set(properties)
            if extra:
                raise SchemaValidationError(f"object at {location} has extra fields: {sorted(extra)}")
        for field_name, definition in properties.items():
            if field_name in value:
                validate_schema_instance(
                    value[field_name],
                    definition,
                    references=references,
                    location=f"{location}.{field_name}",
                )

    any_of = schema.get("anyOf")
    if any_of is not None and not any(
        _schema_matches(value, candidate, references=references, location=location) for candidate in any_of
    ):
        raise SchemaValidationError(f"value at {location} does not match any allowed schema")

    excluded = schema.get("not")
    if excluded is not None and _schema_matches(value, excluded, references=references, location=location):
        raise SchemaValidationError(f"value at {location} matches a forbidden schema")

    for constraint in schema.get("allOf", []):
        validate_schema_instance(value, constraint, references=references, location=location)

    condition = schema.get("if")
    if condition is not None:
        branch = "then" if _schema_matches(value, condition, references=references, location=location) else "else"
        if branch in schema:
            validate_schema_instance(value, schema[branch], references=references, location=location)


def _model_name(value: str) -> str:
    if value.isidentifier() and not keyword.iskeyword(value):
        return value
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    candidate = "".join(part[:1].upper() + part[1:] for part in parts)
    if not candidate or not candidate.isidentifier() or keyword.iskeyword(candidate):
        raise ValueError(f"schema cannot produce a valid model name: {value!r}")
    return candidate


def _python_type(definition: dict[str, Any]) -> str:
    if "enum" in definition:
        values = ", ".join(repr(value) for value in definition["enum"])
        return f"Literal[{values}]"
    schema_type = definition.get("type")
    if isinstance(schema_type, list):
        types = [_python_type({"type": item}) for item in schema_type]
        return " | ".join(dict.fromkeys(types))
    if "$ref" in definition:
        return "dict[str, Any]"
    if schema_type == "string":
        return "str"
    if schema_type == "integer":
        return "int"
    if schema_type == "number":
        return "float"
    if schema_type == "boolean":
        return "bool"
    if schema_type == "array":
        items = definition.get("items")
        item_type = _python_type(items) if isinstance(items, dict) else "Any"
        return f"list[{item_type}]"
    if schema_type == "null":
        return "None"
    if schema_type == "object" or "properties" in definition:
        return "dict[str, Any]"
    return "Any"


def _typescript_type(definition: dict[str, Any]) -> str:
    if "enum" in definition:
        return " | ".join(json.dumps(value) for value in definition["enum"])
    schema_type = definition.get("type")
    if isinstance(schema_type, list):
        types = [_typescript_type({"type": item}) for item in schema_type]
        return " | ".join(dict.fromkeys(types))
    if schema_type == "string":
        return "string"
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "array":
        items = definition.get("items")
        item_type = _typescript_type(items) if isinstance(items, dict) else "unknown"
        return f"Array<{item_type}>"
    if schema_type == "null":
        return "null"
    if schema_type == "object" or "properties" in definition:
        return "Record<string, unknown>"
    return "unknown"


def _python_annotation(definition: dict[str, Any], base_annotation: str | None = None) -> str:
    annotation = _python_type(definition) if base_annotation is None else base_annotation
    constraints = []
    if "minimum" in definition:
        constraints.append(f"ge={definition['minimum']!r}")
    if "maximum" in definition:
        constraints.append(f"le={definition['maximum']!r}")
    if "minItems" in definition:
        constraints.append(f"min_length={definition['minItems']!r}")
    if "pattern" in definition:
        constraints.append(f"pattern={definition['pattern']!r}")
    if constraints:
        return f"Annotated[{annotation}, Field({', '.join(constraints)})]"
    return annotation


def _typescript_constraint_comment(definition: dict[str, Any]) -> str | None:
    constraints = [
        f"minimum: {definition['minimum']}" if "minimum" in definition else None,
        f"maximum: {definition['maximum']}" if "maximum" in definition else None,
        f"minItems: {definition['minItems']}" if "minItems" in definition else None,
        f"pattern: {definition['pattern']}" if "pattern" in definition else None,
    ]
    present = [constraint for constraint in constraints if constraint]
    return f"  /** {'; '.join(present)} */" if present else None


def _validate_definition(definition: dict[str, Any], location: str) -> None:
    unsupported = set(definition) - PROPERTY_KEYWORDS
    if unsupported:
        raise ValueError(f"unsupported schema keyword(s) at {location}: {sorted(unsupported)}")
    if "minimum" in definition and not isinstance(definition["minimum"], int | float):
        raise ValueError(f"minimum must be numeric at {location}")
    if "maximum" in definition and not isinstance(definition["maximum"], int | float):
        raise ValueError(f"maximum must be numeric at {location}")
    if "minItems" in definition and (type(definition["minItems"]) is not int or definition["minItems"] < 0):
        raise ValueError(f"minItems must be a non-negative integer at {location}")
    if "pattern" in definition and not isinstance(definition["pattern"], str):
        raise ValueError(f"pattern must be a string at {location}")
    items = definition.get("items")
    if items is not None:
        if not isinstance(items, dict):
            raise ValueError(f"items must be an object at {location}")
        _validate_definition(items, f"{location}.items")
    properties = definition.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise ValueError(f"properties must be an object at {location}")
        for field_name, nested in properties.items():
            if not isinstance(nested, dict):
                raise ValueError(f"property definition must be an object: {location}.{field_name}")
            _validate_definition(nested, f"{location}.{field_name}")


def _validate_runtime_schema(schema: dict[str, Any], location: str) -> None:
    unsupported = set(schema) - RUNTIME_SCHEMA_KEYWORDS
    if unsupported:
        raise ValueError(f"unsupported runtime schema keyword(s) at {location}: {sorted(unsupported)}")
    required = schema.get("required")
    if required is not None and (
        not isinstance(required, list) or any(not isinstance(field_name, str) for field_name in required)
    ):
        raise ValueError(f"required must be a string list at {location}")
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise ValueError(f"properties must be an object at {location}")
        for field_name, definition in properties.items():
            if not isinstance(definition, dict):
                raise ValueError(f"property definition must be an object: {location}.{field_name}")
            _validate_runtime_schema(definition, f"{location}.{field_name}")
    items = schema.get("items")
    if items is not None:
        if not isinstance(items, dict):
            raise ValueError(f"items must be an object at {location}")
        _validate_runtime_schema(items, f"{location}.items")
    for schema_keyword in ("allOf", "anyOf"):
        branches = schema.get(schema_keyword)
        if branches is not None:
            if not isinstance(branches, list) or not branches:
                raise ValueError(f"{schema_keyword} must be a non-empty list at {location}")
            for index, branch in enumerate(branches, start=1):
                if not isinstance(branch, dict):
                    raise ValueError(f"{schema_keyword} entry must be an object at {location}[{index}]")
                _validate_runtime_schema(branch, f"{location}.{schema_keyword}[{index}]")
    for schema_keyword in ("if", "then", "else", "not"):
        branch = schema.get(schema_keyword)
        if branch is not None:
            if not isinstance(branch, dict):
                raise ValueError(f"{schema_keyword} must be an object at {location}")
            _validate_runtime_schema(branch, f"{location}.{schema_keyword}")


def _conditional_validators(schema: dict[str, Any], name: str) -> tuple[list[str], list[dict[str, Any]]]:
    if name == "mcu_protocol":
        _validate_runtime_schema(schema, name)
        return (
            [
                "",
                '    @model_validator(mode="before")',
                "    @classmethod",
                "    def _validate_mcu_protocol(cls, value):",
                "        validate_schema_instance(value, MCU_PROTOCOL_SCHEMA)",
                "        return value",
                "",
                '    @model_serializer(mode="wrap")',
                "    def _serialize_mcu_protocol(self, handler):",
                "        return {key: item for key, item in handler(self).items() if item is not None}",
            ],
            schema.get("allOf", []),
        )
    lines: list[str] = []
    metadata: list[dict[str, Any]] = []
    for index, conditional in enumerate(schema.get("allOf", []), start=1):
        try:
            condition_properties = conditional["if"]["properties"]
            then_properties = conditional["then"]["properties"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"unsupported allOf conditional in schema {name} at index {index}") from exc
        if len(condition_properties) != 1 or len(then_properties) != 1:
            raise ValueError(f"allOf conditional must target one field in schema {name} at index {index}")
        condition_field, condition = next(iter(condition_properties.items()))
        target_field, constraint = next(iter(then_properties.items()))
        if not isinstance(condition, dict) or set(condition) != {"const"}:
            raise ValueError(f"allOf condition must use one const in schema {name} at index {index}")
        if not isinstance(constraint, dict) or set(constraint) - {"minimum", "maximum"}:
            raise ValueError(f"allOf result must use numeric bounds in schema {name} at index {index}")
        checks = []
        if "minimum" in constraint:
            checks.append(f"self.{target_field} < {constraint['minimum']!r}")
        if "maximum" in constraint:
            checks.append(f"self.{target_field} > {constraint['maximum']!r}")
        if not checks:
            raise ValueError(f"allOf result has no supported bound in schema {name} at index {index}")
        error_message = f"{target_field} violates the {condition_field}={condition['const']!r} constraint"
        lines.extend(
            [
                "",
                '    @model_validator(mode="after")',
                f"    def _validate_conditional_{index}(self):",
                f"        if self.{condition_field} == {condition['const']!r} and ({' or '.join(checks)}):",
                f"            raise ValueError({error_message!r})",
                "        return self",
            ]
        )
        metadata.append(
            {
                "if": {condition_field: condition["const"]},
                "then": {target_field: constraint},
            }
        )
    return lines, metadata


class SchemaCompiler:
    """Generate importable Pydantic models and valid TypeScript interfaces."""

    def __init__(self, schemas_dir: Path):
        self.schemas_dir = schemas_dir
        self.schemas: dict[str, dict[str, Any]] = {}

    def load_schemas(self) -> None:
        self.schemas = {}
        for schema_file in sorted(self.schemas_dir.glob(f"*{SCHEMA_SUFFIX}")):
            name = schema_file.name.removesuffix(SCHEMA_SUFFIX)
            with schema_file.open(encoding="utf-8") as handle:
                schema = json.load(handle)
            if not isinstance(schema, dict):
                raise ValueError(f"schema root must be an object: {schema_file.name}")
            self.schemas[name] = schema

    def _resolve_ref(self, reference: Any, location: str) -> tuple[str, dict[str, Any]]:
        if not isinstance(reference, str) or "/" in reference or "\\" in reference:
            raise ValueError(f"only local schema file references are supported at {location}")
        name = reference.removesuffix(SCHEMA_SUFFIX)
        schema = self.schemas.get(name)
        if schema is None:
            raise ValueError(f"unknown schema reference {reference!r} at {location}")
        return _model_name(schema.get("title", name)), schema

    def _python_base_annotation(
        self,
        definition: dict[str, Any],
        suggested_name: str,
        location: str,
        class_blocks: list[str],
        generated: dict[str, dict[str, Any]],
    ) -> str:
        if "$ref" in definition:
            class_name, referenced_schema = self._resolve_ref(definition["$ref"], location)
            self._append_python_model(class_name, referenced_schema, location, class_blocks, generated)
            return class_name
        schema_type = definition.get("type")
        if schema_type == "array":
            items = definition.get("items")
            if not isinstance(items, dict):
                return "list[Any]"
            item_annotation = self._python_base_annotation(
                items,
                f"{suggested_name}Item",
                f"{location}.items",
                class_blocks,
                generated,
            )
            item_annotation = _python_annotation(items, item_annotation)
            return f"list[{item_annotation}]"
        if schema_type == "object" and isinstance(definition.get("properties"), dict):
            self._append_python_model(suggested_name, definition, location, class_blocks, generated)
            return suggested_name
        return _python_type(definition)

    def _append_python_model(
        self,
        class_name: str,
        schema: dict[str, Any],
        location: str,
        class_blocks: list[str],
        generated: dict[str, dict[str, Any]],
    ) -> None:
        existing = generated.get(class_name)
        if existing is not None:
            if existing != schema:
                raise ValueError(f"generated model name collision for {class_name} at {location}")
            return
        generated[class_name] = schema

        unsupported_root = set(schema) - ROOT_KEYWORDS
        if unsupported_root:
            raise ValueError(f"unsupported schema keyword(s) at {location}: {sorted(unsupported_root)}")
        properties = schema.get("properties", {})
        if schema.get("type") != "object" or not isinstance(properties, dict):
            raise ValueError(f"schema must describe an object at {location}")
        required = set(schema.get("required", []))
        additional_properties = schema.get("additionalProperties", True)
        if type(additional_properties) is not bool:
            raise ValueError(f"additionalProperties must be boolean at {location}")

        fields = []
        for field_name, definition in properties.items():
            if not isinstance(definition, dict):
                raise ValueError(f"property definition must be an object: {location}.{field_name}")
            if not field_name.isidentifier() or keyword.iskeyword(field_name):
                raise ValueError(f"property cannot produce a Python field: {location}.{field_name}")
            field_location = f"{location}.{field_name}"
            _validate_definition(definition, field_location)
            nested_name = f"{class_name}{_model_name(field_name)}"
            base_annotation = self._python_base_annotation(
                definition,
                nested_name,
                field_location,
                class_blocks,
                generated,
            )
            annotation = _python_annotation(definition, base_annotation)
            optional = field_name not in required
            if optional and "None" not in annotation.split(" | "):
                annotation += " | None"
            fields.append(f"    {field_name}: {annotation}{' = None' if optional else ''}")

        conditional_lines, _ = _conditional_validators(schema, location)
        if not additional_properties:
            fields.insert(0, '    model_config = ConfigDict(extra="forbid")')
        body = "\n".join([*fields, *conditional_lines]) or "    pass"
        class_blocks.append(f"class {class_name}(BaseModel):\n{body}\n")

    def compile_all(self, output_py: Path, output_ts: Path) -> None:
        output_py.mkdir(parents=True, exist_ok=True)
        output_ts.mkdir(parents=True, exist_ok=True)

        for name, schema in self.schemas.items():
            unsupported_root = set(schema) - ROOT_KEYWORDS
            if unsupported_root:
                raise ValueError(f"unsupported schema keyword(s) in {name}: {sorted(unsupported_root)}")
            model_name = _model_name(schema.get("title", name))
            properties = schema.get("properties", {})
            if schema.get("type") != "object" or not isinstance(properties, dict):
                raise ValueError(f"schema must describe an object: {name}")
            required = set(schema.get("required", []))
            additional_properties = schema.get("additionalProperties", True)
            if type(additional_properties) is not bool:
                raise ValueError(f"additionalProperties must be boolean in schema {name}")

            typescript_fields = []
            constraint_metadata: dict[str, Any] = {}
            for field_name, definition in properties.items():
                if not isinstance(definition, dict):
                    raise ValueError(f"property definition must be an object: {name}.{field_name}")
                if not field_name.isidentifier() or keyword.iskeyword(field_name):
                    raise ValueError(f"property cannot produce a Python field: {name}.{field_name}")
                _validate_definition(definition, f"{name}.{field_name}")
                optional = field_name not in required
                marker = "" if not optional else "?"
                comment = _typescript_constraint_comment(definition)
                if comment:
                    typescript_fields.append(comment)
                    constraint_metadata[field_name] = {
                        key: definition[key]
                        for key in ("minimum", "maximum", "minItems", "pattern")
                        if key in definition
                    }
                typescript_fields.append(f"  {json.dumps(field_name)}{marker}: {_typescript_type(definition)};")

            _, conditional_metadata = _conditional_validators(schema, name)
            class_blocks: list[str] = []
            self._append_python_model(model_name, schema, name, class_blocks, {})
            pydantic_imports = "BaseModel, ConfigDict, Field, model_validator"
            if name == "mcu_protocol":
                pydantic_imports = "BaseModel, ConfigDict, Field, model_serializer, model_validator"
            python_code = f"from typing import Annotated, Any, Literal\n\nfrom pydantic import {pydantic_imports}\n"
            if name == "mcu_protocol":
                python_code += "from workbench.kernel.schema_compiler import validate_schema_instance\n"
                python_code += f"\n\nMCU_PROTOCOL_SCHEMA = {schema!r}\n"
            python_code += "\n\n" + "\n\n".join(class_blocks)
            typescript_body = "\n".join(typescript_fields)
            metadata = {
                "fields": constraint_metadata,
                "conditionals": conditional_metadata,
                "additionalProperties": additional_properties,
            }
            typescript_code = (
                f"export interface {model_name} {{\n{typescript_body}\n}}\n\n"
                f"export const {model_name}Constraints = {json.dumps(metadata, indent=2)} as const;\n\n"
                f"export const {model_name}Schema = {json.dumps(schema, indent=2)} as const;\n"
            )
            (output_py / f"{name}.py").write_text(python_code, encoding="utf-8")
            (output_ts / f"{name}.ts").write_text(typescript_code, encoding="utf-8")

    def verify_type_compatibility(self) -> dict[str, bool]:
        return {
            name: schema.get("type") == "object" and isinstance(schema.get("properties", {}), dict)
            for name, schema in self.schemas.items()
        }


def compile_schemas(schemas_dir: Path, output_dir: Path) -> bool:
    compiler = SchemaCompiler(schemas_dir)
    compiler.load_schemas()
    compiler.compile_all(output_dir / "python_models", output_dir / "typescript_models")
    return True
