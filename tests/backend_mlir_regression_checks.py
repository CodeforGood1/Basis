from pathlib import Path
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "compiler"))
sys.path.insert(0, str(ROOT / "tests"))

from backend_mlir import BasisMlirBackend
from diagnostics import DiagnosticEngine
from pipeline_support import build_bir_program


def assert_backend_emits_basis_dialect_artifacts():
    source = """#[max_memory(8kb)]
@ffi(lib="basis.test_support")
@deterministic
@stack(64)
extern fn platform_tick() -> u32;

public struct Pair {
    left: i32,
    right: i32,
}

@task(stack=512, priority=2)
@region("iram")
public fn worker() -> void {
    let tick: u32 = platform_tick();
    if tick == 0 as u32 {
        return;
    }
}

fn main() -> i32 {
    let pair: Pair = Pair { left: 1, right: 2 };

    if pair.left > 0 {
        worker();
        return pair.right;
    }

    return 0;
}
"""

    program = build_bir_program(source)
    diag = DiagnosticEngine()
    backend = BasisMlirBackend(diag)
    out_dir = ROOT / "tests" / "_tmp_backend" / f"mlir_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        object_path = backend.generate_all(program, out_dir)
        assert object_path is not None, "MLIR backend did not emit a host object file"
        assert object_path.exists(), "MLIR backend object file missing"
        artifact = (out_dir / "sample_program.mlir").read_text(encoding="utf-8")
        llvm_artifact = (out_dir / "sample_program.llvm.mlir").read_text(encoding="utf-8")
        llvm_ir = (out_dir / "sample_program.ll").read_text(encoding="utf-8")

        assert "basis.program @sample_program" in artifact
        assert "basis.module @sample" in artifact
        assert "basis.struct @Pair" in artifact
        assert "basis.extern @platform_tick" in artifact
        assert "basis.func @worker" in artifact
        assert "basis.isr = #basis.isr<interrupt = false, task_stack = 512, task_priority = 2" in artifact
        assert 'region = "iram"' in artifact
        assert 'callee = "worker"' in artifact
        assert "basis.cond_br" in artifact

        assert "builtin.module" in llvm_artifact
        assert "llvm.module @sample" in llvm_artifact
        assert "llvm.type @Pair = !llvm.struct" in llvm_artifact
        assert "llvm.func @platform_tick" in llvm_artifact
        assert "llvm.func @worker" in llvm_artifact
        assert "llvm.call" in llvm_artifact
        assert "llvm.icmp" in llvm_artifact
        assert "llvm.cond_br" in llvm_artifact
        assert 'define external i32 @"main"()' in llvm_ir
    finally:
        for path in sorted(out_dir.glob("*")):
            path.unlink()
        out_dir.rmdir()


if __name__ == "__main__":
    assert_backend_emits_basis_dialect_artifacts()
    print("MLIR backend regression checks passed.")
