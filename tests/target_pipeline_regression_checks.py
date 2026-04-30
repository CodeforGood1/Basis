from pathlib import Path
import json
import shutil
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "compiler"))

from target_config import PREDEFINED_TARGETS


def run_basis(*args: str):
    result = subprocess.run(
        [sys.executable, "compiler/basis.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def assert_predefined_target_profiles_cover_phase_10_targets():
    expected = {"esp32", "stm32", "rp2040", "embedded_linux"}
    missing = expected.difference(PREDEFINED_TARGETS)
    assert not missing, f"missing Phase 10 target profiles: {sorted(missing)}"


def assert_esp32_c_bundle_generates_idf_project():
    out_dir = ROOT / "tests" / "_tmp_backend" / f"esp32_bundle_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        exit_code, output = run_basis(
            "build",
            "examples/embedded_demo.bs",
            "--backend",
            "c",
            "--emit-c",
            "--target",
            "esp32",
            "-o",
            str(out_dir),
        )
        assert exit_code == 0, output
        manifest_path = out_dir / "basis-target-manifest.json"
        assert manifest_path.exists(), "target manifest missing for esp32 C build"

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["target_key"] == "esp32"
        assert manifest["build_system"] == "esp-idf"
        assert manifest["sdk_integration"] == "esp-idf"
        assert manifest["target_triple"] == "xtensa-esp32-none-elf"
        assert manifest["build"]["steps"][0][0] == "idf.py"
        assert "tool_requirements" in manifest
        assert "support_requirements" in manifest
        assert (out_dir / "basis-build-target.ps1").exists()
        assert (out_dir / "basis-flash-target.ps1").exists()
        assert (out_dir / "basis-validate-target.ps1").exists()
        assert (out_dir / "basis-validate-target.sh").exists()
        assert (out_dir / "esp32_project" / "CMakeLists.txt").exists()
        assert (out_dir / "esp32_project" / "main" / "CMakeLists.txt").exists()
        assert (out_dir / "esp32_project" / "main" / "idf_component.yml").exists()
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def assert_embedded_linux_llvm_bundle_generates_toolchain_wrappers():
    out_dir = ROOT / "tests" / "_tmp_backend" / f"linux_llvm_bundle_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        exit_code, output = run_basis(
            "build",
            "examples/hello.bs",
            "--backend",
            "llvm",
            "--emit-c",
            "--target",
            "embedded_linux",
            "-o",
            str(out_dir),
        )
        assert exit_code == 0, output
        manifest_path = out_dir / "basis-target-manifest.json"
        assert manifest_path.exists(), "target manifest missing for embedded Linux LLVM build"

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["target_key"] == "embedded_linux"
        assert manifest["target_triple"] == "x86_64-pc-linux-gnu"
        assert manifest["artifact_format"] == "elf"
        assert manifest["build"]["steps"][0][0] == "x86_64-linux-gnu-gcc"
        assert any(artifact["kind"] == "llvm_ir" for artifact in manifest["artifacts"])
        assert any(artifact["kind"] == "object" for artifact in manifest["artifacts"])
        assert (out_dir / "basis-build-target.sh").exists()
        assert (out_dir / "basis-run-target.ps1").exists()
        assert (out_dir / "basis-validate-target.sh").exists()
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def assert_stm32_c_bundle_generates_linker_and_startup_scaffolding():
    out_dir = ROOT / "tests" / "_tmp_backend" / f"stm32_bundle_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        exit_code, output = run_basis(
            "build",
            "examples/embedded_demo.bs",
            "--backend",
            "c",
            "--emit-c",
            "--target",
            "stm32",
            "-o",
            str(out_dir),
        )
        assert exit_code == 0, output
        manifest = json.loads((out_dir / "basis-target-manifest.json").read_text(encoding="utf-8"))
        assert manifest["target_key"] == "stm32"
        assert manifest["linker_script_required"] is True
        assert any(item["kind"] == "linker_script" for item in manifest["support_requirements"])
        assert any(item["kind"] == "startup_object" for item in manifest["support_requirements"])
        assert (out_dir / "target-support" / "linker_script.ld.template").exists()
        assert (out_dir / "target-support" / "startup" / "README.txt").exists()
        assert manifest["build"]["steps"][0][0] == "arm-none-eabi-gcc"
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def assert_host_llvm_bundle_validation_script_passes():
    out_dir = ROOT / "tests" / "_tmp_backend" / f"host_llvm_validate_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        exit_code, output = run_basis(
            "build",
            "examples/hello.bs",
            "--backend",
            "llvm",
            "--emit-c",
            "-o",
            str(out_dir),
        )
        assert exit_code == 0, output
        validate = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(out_dir / "basis-validate-target.ps1")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        combined = (validate.stdout or "") + (validate.stderr or "")
        assert validate.returncode == 0, combined
        assert "Target bundle validation passed." in combined
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    assert_predefined_target_profiles_cover_phase_10_targets()
    assert_esp32_c_bundle_generates_idf_project()
    assert_embedded_linux_llvm_bundle_generates_toolchain_wrappers()
    assert_stm32_c_bundle_generates_linker_and_startup_scaffolding()
    assert_host_llvm_bundle_validation_script_passes()
    print("Target pipeline regression checks passed.")
