"""
BASIS MLIR backend scaffolding.

Phase 5 deliberately keeps BASIS semantics in the validated frontend and BIR.
This backend emits a structured textual BASIS dialect artifact from BIR so later
Phase 6 conversions can lower it further without changing language meaning.
"""

from pathlib import Path
from typing import Optional

from diagnostics import DiagnosticEngine
from bir.model import Program
from mlir_conversions.bir_to_basis import convert_program_to_basis_mlir
from mlir_conversions.verify import BasisMlirVerificationError, verify_basis_mlir_program
from mlir_dialects.basis import render_basis_mlir_program


class BasisMlirBackendError(ValueError):
    """Raised when valid BIR cannot be emitted as textual BASIS MLIR."""


class BasisMlirBackend:
    def __init__(self, diag_engine: DiagnosticEngine, export_all: bool = False):
        self.diag = diag_engine
        self.export_all = export_all
        self.program: Optional[Program] = None

    def generate_all(self, program: Program, output_dir: Path) -> bool:
        self.program = program
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            basis_mlir_program = convert_program_to_basis_mlir(program, export_all=self.export_all)
            verify_basis_mlir_program(basis_mlir_program)
        except BasisMlirVerificationError as exc:
            raise BasisMlirBackendError(str(exc)) from exc

        artifact_path = output_dir / f"{program.name}.mlir"
        artifact_path.write_text(render_basis_mlir_program(basis_mlir_program), encoding="utf-8")
        return True
