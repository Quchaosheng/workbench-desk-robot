import sys
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "kernel"))

from workbench.kernel.schema_compiler import SchemaCompiler


def test_generated_models_are_valid_and_typed(tmp_path: Path) -> None:
    compiler = SchemaCompiler(ROOT / "interfaces" / "json_schema")
    compiler.load_schemas()

    python_dir = tmp_path / "python"
    typescript_dir = tmp_path / "typescript"
    compiler.compile_all(python_dir, typescript_dir)

    generated = python_dir / "action_result.py"
    namespace = {}
    exec(compile(generated.read_text(encoding="utf-8"), str(generated), "exec"), namespace)
    model = namespace["ActionResult"]
    assert issubclass(model, BaseModel)
    assert model.model_fields["action_id"].is_required()
    assert not model.model_fields["error_code"].is_required()

    typescript = (typescript_dir / "action_result.ts").read_text(encoding="utf-8")
    assert "export interface ActionResult {" in typescript
    assert '"action_id": string;' in typescript
    assert '"error_code"?: number | null;' in typescript
    assert all(compiler.verify_type_compatibility().values())
