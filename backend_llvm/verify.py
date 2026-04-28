"""
Verification for the textual LLVM IR model emitted by the Phase 7 backend.
"""

from typing import Set

from .llvm_ir import LlvmIrModule


class LlvmIrVerificationError(ValueError):
    """Raised when the structured LLVM IR model is invalid."""


def verify_llvm_ir_module(module: LlvmIrModule):
    if not module.source_filename:
        raise LlvmIrVerificationError("LLVM IR module source_filename must be non-empty")
    if not module.target_triple:
        raise LlvmIrVerificationError("LLVM IR module target_triple must be non-empty")

    global_names: Set[str] = set()
    for global_value in module.globals:
        if global_value.name in global_names:
            raise LlvmIrVerificationError(f"duplicate LLVM IR global '@{global_value.name}'")
        global_names.add(global_value.name)

    symbol_names: Set[str] = set()
    for declare in module.declarations:
        if declare.name in symbol_names:
            raise LlvmIrVerificationError(f"duplicate LLVM IR declaration '@{declare.name}'")
        symbol_names.add(declare.name)
    for function in module.functions:
        if function.name in symbol_names:
            raise LlvmIrVerificationError(f"duplicate LLVM IR function '@{function.name}'")
        symbol_names.add(function.name)
        if not function.blocks:
            raise LlvmIrVerificationError(f"LLVM IR function '@{function.name}' must contain blocks")
        block_names = {block.label for block in function.blocks}
        if len(block_names) != len(function.blocks):
            raise LlvmIrVerificationError(f"LLVM IR function '@{function.name}' has duplicate blocks")
