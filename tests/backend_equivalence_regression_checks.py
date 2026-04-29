from pathlib import Path
import json
import shutil
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]


def run_basis(*args: str):
    result = subprocess.run(
        [sys.executable, "compiler/basis.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def _read_manifest(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def assert_host_backend_manifests_stay_aligned():
    out_dir = ROOT / "tests" / "_tmp_backend" / f"equiv_host_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        exit_code, output = run_basis(
            "build",
            "examples/hello.bs",
            "--emit-c",
            "--compare-backends",
            "c,mlir,llvm",
            "-o",
            str(out_dir),
        )
        assert exit_code == 0, output

        c_manifest = _read_manifest(out_dir / "c" / "basis-target-manifest.json")
        mlir_manifest = _read_manifest(out_dir / "mlir" / "basis-target-manifest.json")
        llvm_manifest = _read_manifest(out_dir / "llvm" / "basis-target-manifest.json")

        for manifest in (c_manifest, mlir_manifest, llvm_manifest):
            assert manifest["target_key"] == "host"
            assert manifest["startup_model"] == "hosted"
            assert manifest["supports_host_run"] is True
            assert manifest["target_triple"] == "native"
            assert manifest["target_abi"] == "system"

        assert c_manifest["backend"] == "c"
        assert mlir_manifest["backend"] == "mlir"
        assert llvm_manifest["backend"] == "llvm"
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def assert_embedded_backend_manifests_stay_aligned():
    out_dir = ROOT / "tests" / "_tmp_backend" / f"equiv_esp32_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        source_path = out_dir / "esp32_equiv.bs"
        source_path.write_text(
            "#[max_memory(8kb)]\n\nfn main() -> void {\n    return;\n}\n",
            encoding="utf-8",
        )
        exit_code, output = run_basis(
            "build",
            str(source_path),
            "--emit-c",
            "--target",
            "esp32",
            "--compare-backends",
            "c,mlir,llvm",
            "-o",
            str(out_dir),
        )
        assert exit_code == 0, output

        manifests = [
            _read_manifest(out_dir / backend / "basis-target-manifest.json")
            for backend in ("c", "mlir", "llvm")
        ]
        for manifest in manifests:
            assert manifest["target_key"] == "esp32"
            assert manifest["startup_model"] == "target_alias"
            assert manifest["supports_host_run"] is False
            assert manifest["target_triple"] == "xtensa-esp32-none-elf"
            assert manifest["target_abi"] == "xtensa-call0"
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    assert_host_backend_manifests_stay_aligned()
    assert_embedded_backend_manifests_stay_aligned()
    print("Backend equivalence regression checks passed.")
