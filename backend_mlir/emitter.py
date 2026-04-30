"""
MLIR backend that preserves MLIR artifacts and emits real LLVM deliverables.
"""

from pathlib import Path
from typing import Optional

from diagnostics import DiagnosticEngine
from bir.model import Program
from backend_llvm.pipeline import (
    LlvmArtifactPipelineError,
    generate_llvm_artifacts,
    write_llvm_artifacts,
)


class BasisMlirBackendError(ValueError):
    """Raised when valid BIR cannot be emitted as textual BASIS MLIR."""


class BasisMlirBackend:
    def __init__(self, diag_engine: DiagnosticEngine, export_all: bool = False):
        self.diag = diag_engine
        self.export_all = export_all
        self.program: Optional[Program] = None

    def generate_all(self, program: Program, output_dir: Path) -> Optional[Path]:
        self.program = program
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            artifacts = generate_llvm_artifacts(program, export_all=self.export_all)
        except LlvmArtifactPipelineError as exc:
            raise BasisMlirBackendError(str(exc)) from exc

        return write_llvm_artifacts(output_dir, program.name, artifacts)
