from pathlib import Path
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "compiler"))
sys.path.insert(0, str(ROOT / "tests"))

from backend_llvm import BasisLlvmBackend
from diagnostics import DiagnosticEngine
from pipeline_support import build_bir_program


def assert_backend_emits_real_llvm_ir_and_object():
    source = """#[max_memory(4kb)]
fn plus_one(x: i32) -> i32 {
    return x + 1;
}

fn main() -> i32 {
    let value: i32 = plus_one(4);
    if value > 3 {
        return value;
    }
    return 0;
}
"""

    program = build_bir_program(source)
    diag = DiagnosticEngine()
    backend = BasisLlvmBackend(diag)
    out_dir = ROOT / "tests" / "_tmp_backend" / f"llvm_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        object_path = backend.generate_all(program, out_dir)
        assert object_path is not None, "LLVM backend did not emit an object file"
        assert object_path.exists(), "LLVM backend object file missing"

        llvm_ir = (out_dir / "sample_program.ll").read_text(encoding="utf-8")
        lowered_mlir = (out_dir / "sample_program.llvm.mlir").read_text(encoding="utf-8")

        assert 'define external i32 @"sample.main"()' in llvm_ir
        assert 'define internal i32 @"sample.plus_one"(i32 %"x")' in llvm_ir
        assert "add i32" in llvm_ir
        assert "icmp sgt i32" in llvm_ir
        assert "br i1" in llvm_ir
        assert "ret i32" in llvm_ir
        assert "llvm.func @plus_one" in lowered_mlir
        assert "llvm.add" in lowered_mlir
    finally:
        for path in sorted(out_dir.glob("*")):
            path.unlink()
        out_dir.rmdir()


if __name__ == "__main__":
    assert_backend_emits_real_llvm_ir_and_object()
    print("LLVM backend regression checks passed.")
