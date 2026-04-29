from pathlib import Path
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "compiler"))
sys.path.insert(0, str(ROOT / "tests"))

from backend_c import BirCBackend
from diagnostics import DiagnosticEngine
from pipeline_support import build_bir_program


def assert_backend_emits_structs_strings_and_cfg():
    source = """#[max_memory(8kb)]
@ffi(lib="basis.test_support")
@deterministic
@blocking
@stack(64)
extern fn print_str(s: *u8) -> void;

public struct Pair {
    left: i32,
    right: i32,
}

fn main() -> i32 {
    let pair: Pair = Pair { left: 1, right: 2 };

    if pair.left > 0 {
        print_str("ok\\n");
        return pair.right;
    }

    return 0;
}
"""

    program = build_bir_program(source)
    diag = DiagnosticEngine()
    backend = BirCBackend(diag)
    out_dir = ROOT / "tests" / "_tmp_backend" / f"structs_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        assert backend.generate_all(program, out_dir), "backend unexpectedly failed"
        impl = (out_dir / "sample.c").read_text(encoding="utf-8")
        header = (out_dir / "sample.h").read_text(encoding="utf-8")

        assert "typedef struct Pair Pair;" in header
        assert 'print_str("ok\\n");' in impl
        assert "entry:" in impl
        assert "if_then_" in impl

        result = subprocess.run(
            ["gcc", "-std=c99", "-c", str(out_dir / "sample.c"), "-o", str(out_dir / "sample.o")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout
    finally:
        for path in sorted(out_dir.glob("*")):
            path.unlink()
        out_dir.rmdir()


def assert_backend_emits_volatile_pointer_types():
    source = """#[max_memory(4kb)]
fn main() -> i32 {
    let gpio_out: volatile *u32 = 0x3FF44004 as volatile *u32;
    return (*gpio_out) as i32;
}
"""

    program = build_bir_program(source)
    diag = DiagnosticEngine()
    backend = BirCBackend(diag)
    out_dir = ROOT / "tests" / "_tmp_backend" / f"volatile_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        assert backend.generate_all(program, out_dir), "backend unexpectedly failed"
        impl = (out_dir / "sample.c").read_text(encoding="utf-8")
        assert "volatile uint32_t* slot_gpio_out_0;" in impl
        assert "= *tmp" in impl

        result = subprocess.run(
            ["gcc", "-std=c99", "-c", str(out_dir / "sample.c"), "-o", str(out_dir / "sample.o")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout
    finally:
        for path in sorted(out_dir.glob("*")):
            path.unlink()
        out_dir.rmdir()


def assert_backend_emits_runtime_entry_wrappers():
    source = """#[max_memory(4kb)]
fn main() -> void {
    return;
}
"""

    host_program = build_bir_program(source, target_id="host")
    esp32_program = build_bir_program(source, target_id="esp32")
    diag = DiagnosticEngine()
    backend = BirCBackend(diag)
    out_dir = ROOT / "tests" / "_tmp_backend" / f"runtime_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        assert backend.generate_all(host_program, out_dir), "host backend generation failed"
        host_impl = (out_dir / "sample.c").read_text(encoding="utf-8")
        assert "void basis_entry__sample__main(void)" in host_impl
        assert "int main(void)" in host_impl
        assert "basis_entry__sample__main();" in host_impl
    finally:
        for path in sorted(out_dir.glob("*")):
            path.unlink()

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        assert backend.generate_all(esp32_program, out_dir), "esp32 backend generation failed"
        esp32_impl = (out_dir / "sample.c").read_text(encoding="utf-8")
        assert "void basis_entry__sample__main(void)" in esp32_impl
        assert "void app_main(void)" in esp32_impl
        assert "basis_entry__sample__main();" in esp32_impl
    finally:
        for path in sorted(out_dir.glob("*")):
            path.unlink()
        out_dir.rmdir()


if __name__ == "__main__":
    assert_backend_emits_structs_strings_and_cfg()
    assert_backend_emits_volatile_pointer_types()
    assert_backend_emits_runtime_entry_wrappers()
    print("C backend regression checks passed.")
