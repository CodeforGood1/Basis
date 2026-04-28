from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run_basis(*args: str):
    result = subprocess.run(
        [sys.executable, "compiler/basis.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def assert_backend_c_explicit_flag_works():
    exit_code, output = run_basis("build", "examples/hello.bs", "--backend", "c", "--emit-c")
    assert exit_code == 0, output
    assert "Generated C code in" in output


def assert_backend_mlir_explicit_flag_works():
    exit_code, output = run_basis("build", "examples/hello.bs", "--backend", "mlir", "--emit-c")
    assert exit_code == 0, output
    assert "Generated MLIR artifacts in" in output


def assert_unimplemented_llvm_backend_fails_fast():
    exit_code, output = run_basis("build", "examples/hello.bs", "--backend", "llvm", "--emit-c")
    assert exit_code != 0, output
    assert "backend 'llvm' is not implemented yet" in output


def assert_compare_mode_reports_backend_status():
    exit_code, output = run_basis(
        "build",
        "tests/cases/heuristic_budget_emit_c.bs",
        "--emit-c",
        "--compare-backends",
        "c,mlir",
    )
    assert exit_code == 0, output
    assert "BACKEND COMPARISON" in output
    assert "backend c: ok" in output
    assert "backend mlir: ok" in output


def assert_compare_mode_rejects_run():
    exit_code, output = run_basis(
        "build",
        "examples/hello.bs",
        "--compare-backends",
        "c",
        "--run",
    )
    assert exit_code != 0, output
    assert "--run cannot be used with --compare-backends" in output


def assert_run_rejected_for_mlir_backend():
    exit_code, output = run_basis("build", "examples/hello.bs", "--backend", "mlir", "--run")
    assert exit_code != 0, output
    assert "--run is only supported with --backend=c" in output


if __name__ == "__main__":
    assert_backend_c_explicit_flag_works()
    assert_backend_mlir_explicit_flag_works()
    assert_unimplemented_llvm_backend_fails_fast()
    assert_compare_mode_reports_backend_status()
    assert_compare_mode_rejects_run()
    assert_run_rejected_for_mlir_backend()
    print("Backend selection regression checks passed.")
