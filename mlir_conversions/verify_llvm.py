"""
Verification for the Phase 6 LLVM-dialect-style MLIR model.
"""

from typing import Set

from mlir_dialects.llvm import LlvmMlirBlock, LlvmMlirFunction, LlvmMlirModule, LlvmMlirOp, LlvmMlirProgram


class LlvmMlirVerificationError(ValueError):
    """Raised when the Phase 6 LLVM-dialect model is structurally invalid."""


_ALLOWED_OP_PREFIXES = (
    "llvm.add",
    "llvm.sub",
    "llvm.mul",
    "llvm.sdiv",
    "llvm.udiv",
    "llvm.fdiv",
    "llvm.srem",
    "llvm.urem",
    "llvm.frem",
    "llvm.and",
    "llvm.or",
    "llvm.xor",
    "llvm.shl",
    "llvm.ashr",
    "llvm.lshr",
    "llvm.neg",
    "llvm.not",
    "llvm.fadd",
    "llvm.fsub",
    "llvm.fmul",
    "llvm.icmp",
    "llvm.fcmp",
    "llvm.cast",
    "llvm.call",
    "llvm.load",
    "llvm.store",
    "llvm.addressof",
    "llvm.extractvalue",
    "llvm.insertvalue",
    "llvm.mlir.undef",
    "llvm.basis.array_repeat",
    "llvm.return",
    "llvm.br",
    "llvm.cond_br",
    "llvm.unreachable",
)


def verify_llvm_mlir_program(program: LlvmMlirProgram):
    if not program.name:
        raise LlvmMlirVerificationError("LLVM MLIR program name must be non-empty")
    if not program.modules:
        raise LlvmMlirVerificationError("LLVM MLIR program must contain at least one module")
    module_names: Set[str] = set()
    for module in program.modules:
        if module.name in module_names:
            raise LlvmMlirVerificationError(f"duplicate LLVM MLIR module '{module.name}'")
        module_names.add(module.name)
        _verify_module(module)


def _verify_module(module: LlvmMlirModule):
    type_names: Set[str] = set()
    for type_decl in module.type_decls:
        if type_decl.name in type_names:
            raise LlvmMlirVerificationError(f"duplicate LLVM type declaration '{module.name}::{type_decl.name}'")
        type_names.add(type_decl.name)

    symbol_names: Set[str] = set()
    for extern_fn in module.externs:
        if extern_fn.name in symbol_names:
            raise LlvmMlirVerificationError(f"duplicate LLVM symbol '{module.name}::{extern_fn.name}'")
        symbol_names.add(extern_fn.name)
    for function in module.functions:
        if function.name in symbol_names:
            raise LlvmMlirVerificationError(f"duplicate LLVM symbol '{module.name}::{function.name}'")
        symbol_names.add(function.name)
        _verify_function(module.name, function)


def _verify_function(module_name: str, function: LlvmMlirFunction):
    if not function.blocks:
        raise LlvmMlirVerificationError(f"LLVM function '{module_name}::{function.name}' must contain blocks")
    known_blocks = {block.label for block in function.blocks}
    if len(known_blocks) != len(function.blocks):
        raise LlvmMlirVerificationError(f"LLVM function '{module_name}::{function.name}' has duplicate block labels")
    for block in function.blocks:
        _verify_block(module_name, function.name, block, known_blocks)


def _verify_block(module_name: str, function_name: str, block: LlvmMlirBlock, known_blocks: Set[str]):
    if not block.ops:
        raise LlvmMlirVerificationError(f"LLVM block '{module_name}::{function_name}::{block.label}' must not be empty")
    for op in block.ops:
        _verify_op(module_name, function_name, block.label, op, known_blocks)


def _verify_op(module_name: str, function_name: str, block_name: str, op: LlvmMlirOp, known_blocks: Set[str]):
    if not op.op_name.startswith(_ALLOWED_OP_PREFIXES):
        raise LlvmMlirVerificationError(
            f"LLVM op '{module_name}::{function_name}::{block_name}' is not legal in the current Phase 6 pipeline: {op.op_name}"
        )
    for target in op.successors:
        if target not in known_blocks:
            raise LlvmMlirVerificationError(
                f"LLVM op '{module_name}::{function_name}::{block_name}' targets unknown block '{target}'"
            )
