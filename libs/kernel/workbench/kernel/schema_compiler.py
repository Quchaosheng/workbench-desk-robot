"""K1-K2: compile object-shaped JSON Schemas to Python and TypeScript models."""

import json
import keyword
import re
from pathlib import Path
from typing import Any

SCHEMA_SUFFIX = ".schema.json"


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

    def compile_all(self, output_py: Path, output_ts: Path) -> None:
        output_py.mkdir(parents=True, exist_ok=True)
        output_ts.mkdir(parents=True, exist_ok=True)

        for name, schema in self.schemas.items():
            model_name = _model_name(schema.get("title", name))
            properties = schema.get("properties", {})
            if schema.get("type") != "object" or not isinstance(properties, dict):
                raise ValueError(f"schema must describe an object: {name}")
            required = set(schema.get("required", []))

            python_fields = []
            typescript_fields = []
            for field_name, definition in properties.items():
                if not isinstance(definition, dict):
                    raise ValueError(f"property definition must be an object: {name}.{field_name}")
                if not field_name.isidentifier() or keyword.iskeyword(field_name):
                    raise ValueError(f"property cannot produce a Python field: {name}.{field_name}")
                python_annotation = _python_type(definition)
                optional = field_name not in required
                if optional and "None" not in python_annotation.split(" | "):
                    python_annotation += " | None"
                default = "" if not optional else " = None"
                python_fields.append(f"    {field_name}: {python_annotation}{default}")
                marker = "" if not optional else "?"
                typescript_fields.append(f"  {json.dumps(field_name)}{marker}: {_typescript_type(definition)};")

            python_body = "\n".join(python_fields) or "    pass"
            python_code = (
                "from typing import Any, Literal\n\n"
                "from pydantic import BaseModel\n\n\n"
                f"class {model_name}(BaseModel):\n{python_body}\n"
            )
            typescript_body = "\n".join(typescript_fields)
            typescript_code = f"export interface {model_name} {{\n{typescript_body}\n}}\n"
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
