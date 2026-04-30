"""
Shared LLVM artifact pipeline for the LLVM and MLIR backends.

Both backends preserve BASIS semantics in the validated frontend/BIR layers and
then pass through the same verified MLIR conversion stages before producing real
LLVM IR and, when supported, host object files.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from llvmlite import binding as llvm

from bir.model import Program
from mlir_conversions.basis_to_llvm import BasisToLlvmLoweringError, convert_basis_to_llvm_mlir
from mlir_conversions.bir_to_basis import convert_program_to_basis_mlir
from mlir_conversions.canonicalize import canonicalize_basis_mlir_program
from mlir_conversions.verify import BasisMlirVerificationError, verify_basis_mlir_program
from mlir_conversions.verify_llvm import LlvmMlirVerificationError, verify_llvm_mlir_program
from mlir_dialects.basis import render_basis_mlir_program
from mlir_dialects.llvm import render_llvm_mlir_program

from .llvmlite_builder import LlvmLiteLoweringError, LlvmLiteProgramBuilder


class LlvmArtifactPipelineError(ValueError):
    """Raised when verified BIR cannot be turned into LLVM artifacts."""


@dataclass(frozen=True)
class GeneratedLlvmArtifacts:
    basis_mlir_text: str
    llvm_mlir_text: str
    llvm_ir_text: str
    object_bytes: Optional[bytes]


def generate_llvm_artifacts(program: Program, *, export_all: bool = False) -> GeneratedLlvmArtifacts:
    try:
        basis_mlir_program = convert_program_to_basis_mlir(program, export_all=export_all)
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
        raise LlvmArtifactPipelineError(str(exc)) from exc

    try:
        builder = LlvmLiteProgramBuilder(program)
        llvm_module = builder.build()
        llvm.initialize()
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()
        module_ref = llvm.parse_assembly(str(llvm_module))
        module_ref.verify()
        object_bytes = builder.emit_object() if program.runtime.supports_host_run else None
    except (LlvmLiteLoweringError, RuntimeError) as exc:
        raise LlvmArtifactPipelineError(str(exc)) from exc

    return GeneratedLlvmArtifacts(
        basis_mlir_text=render_basis_mlir_program(canonical_program),
        llvm_mlir_text=render_llvm_mlir_program(llvm_mlir_program),
        llvm_ir_text=str(llvm_module),
        object_bytes=object_bytes,
    )


def write_llvm_artifacts(output_dir: Path, program_name: str, artifacts: GeneratedLlvmArtifacts) -> Optional[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{program_name}.mlir").write_text(artifacts.basis_mlir_text, encoding="utf-8")
    (output_dir / f"{program_name}.llvm.mlir").write_text(artifacts.llvm_mlir_text, encoding="utf-8")
    (output_dir / f"{program_name}.ll").write_text(artifacts.llvm_ir_text, encoding="utf-8")
    if artifacts.object_bytes is None:
        return None
    object_path = output_dir / f"{program_name}.o"
    object_path.write_bytes(artifacts.object_bytes)
    return object_path
