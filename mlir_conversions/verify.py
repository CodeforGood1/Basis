"""
Verification for the textual BASIS MLIR model.
"""

from typing import Set

from mlir_dialects.basis import BasisMlirBlock, BasisMlirFunction, BasisMlirModule, BasisMlirOp, BasisMlirProgram


class BasisMlirVerificationError(ValueError):
    """Raised when the Phase 5 BASIS MLIR model is structurally invalid."""


def verify_basis_mlir_program(program: BasisMlirProgram):
    if not program.name:
        raise BasisMlirVerificationError("MLIR program name must be non-empty")
    if not program.target:
        raise BasisMlirVerificationError("MLIR program target must be non-empty")
    if not program.modules:
        raise BasisMlirVerificationError("MLIR program must contain at least one module")

    module_names: Set[str] = set()
    for module in program.modules:
        _verify_module(module)
        if module.name in module_names:
            raise BasisMlirVerificationError(f"duplicate MLIR module '{module.name}'")
        module_names.add(module.name)


def _verify_module(module: BasisMlirModule):
    if not module.name:
        raise BasisMlirVerificationError("MLIR module name must be non-empty")

    struct_names: Set[str] = set()
    for struct_def in module.structs:
        if struct_def.name in struct_names:
            raise BasisMlirVerificationError(f"duplicate MLIR struct '{module.name}::{struct_def.name}'")
        struct_names.add(struct_def.name)

    symbol_names: Set[str] = set()
    for extern_fn in module.externs:
        if extern_fn.name in symbol_names:
            raise BasisMlirVerificationError(f"duplicate MLIR symbol '{module.name}::{extern_fn.name}'")
        symbol_names.add(extern_fn.name)
    for function in module.functions:
        _verify_function(module.name, function)
        if function.name in symbol_names:
            raise BasisMlirVerificationError(f"duplicate MLIR symbol '{module.name}::{function.name}'")
        symbol_names.add(function.name)


def _verify_function(module_name: str, function: BasisMlirFunction):
    if not function.blocks:
        raise BasisMlirVerificationError(f"MLIR function '{module_name}::{function.name}' must contain blocks")
    known_blocks = {block.label for block in function.blocks}
    if len(known_blocks) != len(function.blocks):
        raise BasisMlirVerificationError(f"MLIR function '{module_name}::{function.name}' has duplicate block labels")
    for block in function.blocks:
        _verify_block(module_name, function.name, block, known_blocks)


def _verify_block(module_name: str, function_name: str, block: BasisMlirBlock, known_blocks: Set[str]):
    if not block.ops:
        raise BasisMlirVerificationError(f"MLIR block '{module_name}::{function_name}::{block.label}' must not be empty")
    for op in block.ops:
        _verify_op(module_name, function_name, block.label, op, known_blocks)


def _verify_op(module_name: str, function_name: str, block_name: str, op: BasisMlirOp, known_blocks: Set[str]):
    if not op.op_name.startswith("basis."):
        raise BasisMlirVerificationError(
            f"MLIR op '{module_name}::{function_name}::{block_name}' must stay in the basis dialect"
        )
    for target in op.successors:
        if target not in known_blocks:
            raise BasisMlirVerificationError(
                f"MLIR op '{module_name}::{function_name}::{block_name}' targets unknown block '{target}'"
            )
