"""
Minimal canonicalization/cleanup passes for the Phase 5 BASIS MLIR model.
"""

from dataclasses import replace
from typing import Dict, List

from mlir_dialects.basis import (
    BasisMlirBlock,
    BasisMlirFunction,
    BasisMlirModule,
    BasisMlirOp,
    BasisMlirProgram,
)


def canonicalize_basis_mlir_program(program: BasisMlirProgram) -> BasisMlirProgram:
    return replace(
        program,
        modules=[_canonicalize_module(module) for module in program.modules],
    )


def _canonicalize_module(module: BasisMlirModule) -> BasisMlirModule:
    return replace(
        module,
        functions=[_canonicalize_function(function) for function in module.functions],
    )


def _canonicalize_function(function: BasisMlirFunction) -> BasisMlirFunction:
    return replace(
        function,
        blocks=[_canonicalize_block(block) for block in function.blocks],
    )


def _canonicalize_block(block: BasisMlirBlock) -> BasisMlirBlock:
    return replace(
        block,
        ops=[_canonicalize_op(op) for op in block.ops],
    )


def _canonicalize_op(op: BasisMlirOp) -> BasisMlirOp:
    attrs: Dict[str, str] = dict(op.attrs)
    if op.op_name == "basis.call" and "callee" in attrs:
        attrs.pop("opcode", None)
    if op.op_name == "basis.ret" and not op.operands and op.result_type == "none":
        return replace(op, attrs=attrs, result_type=None)
    if op.op_name != "basis.call":
        attrs.pop("callee", None)
    return replace(op, attrs=attrs)
