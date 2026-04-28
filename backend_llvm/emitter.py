"""
Phase 7 LLVM backend using real LLVM IR generation via llvmlite.
"""

from pathlib import Path
from typing import Optional

from llvmlite import binding as llvm

from diagnostics import DiagnosticEngine
from bir.model import Program
from mlir_conversions.basis_to_llvm import BasisToLlvmLoweringError, convert_basis_to_llvm_mlir
from mlir_conversions.bir_to_basis import convert_program_to_basis_mlir
from mlir_conversions.canonicalize import canonicalize_basis_mlir_program
from mlir_conversions.verify import BasisMlirVerificationError, verify_basis_mlir_program
from mlir_conversions.verify_llvm import LlvmMlirVerificationError, verify_llvm_mlir_program
from mlir_dialects.basis import render_basis_mlir_program
from mlir_dialects.llvm import render_llvm_mlir_program

from .llvmlite_builder import LlvmLiteLoweringError, LlvmLiteProgramBuilder


class BasisLlvmBackendError(ValueError):
    """Raised when valid BIR cannot be emitted as LLVM artifacts."""


class BasisLlvmBackend:
    def __init__(self, diag_engine: DiagnosticEngine, export_all: bool = False):
        self.diag = diag_engine
        self.export_all = export_all
        self.program: Optional[Program] = None

    def generate_all(self, program: Program, output_dir: Path) -> Optional[Path]:
        self.program = program
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            basis_mlir_program = convert_program_to_basis_mlir(program, export_all=self.export_all)
            verify_basis_mlir_program(basis_mlir_program)
            canonical_program = canonicalize_basis_mlir_program(basis_mlir_program)
            verify_basis_mlir_program(canonical_program)
            llvm_mlir_program = convert_basis_to_llvm_mlir(canonical_program)
            verify_llvm_mlir_program(llvm_mlir_program)
        except (
            BasisMlirVerificationError,
            BasisToLlvmLoweringError,
            LlvmMlirVerificationError,
        ) as exc:
            raise BasisLlvmBackendError(str(exc)) from exc

        try:
            builder = LlvmLiteProgramBuilder(program)
            llvm_module = builder.build()
            llvm.initialize()
            llvm.initialize_native_target()
            llvm.initialize_native_asmprinter()
            module_ref = llvm.parse_assembly(str(llvm_module))
            module_ref.verify()
            object_bytes = builder.emit_object() if program.target == "host" else None
        except (LlvmLiteLoweringError, RuntimeError) as exc:
            raise BasisLlvmBackendError(str(exc)) from exc

        (output_dir / f"{program.name}.mlir").write_text(render_basis_mlir_program(canonical_program), encoding="utf-8")
        (output_dir / f"{program.name}.llvm.mlir").write_text(
            render_llvm_mlir_program(llvm_mlir_program), encoding="utf-8"
        )
        ll_path = output_dir / f"{program.name}.ll"
        ll_path.write_text(str(llvm_module), encoding="utf-8")

        if object_bytes is None:
            return None
        object_path = output_dir / f"{program.name}.o"
        object_path.write_bytes(object_bytes)
        return object_path
