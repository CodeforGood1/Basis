"""
Lower the Phase 5 BASIS MLIR model toward an LLVM-dialect-style MLIR model.
"""

import json
from typing import Dict, List, Optional

from mlir_conversions.type_converter import LoweredTypeInfo, lower_basis_type
from mlir_dialects.basis import (
    BasisMlirBlock,
    BasisMlirExtern,
    BasisMlirFunction,
    BasisMlirGlobal,
    BasisMlirModule,
    BasisMlirOp,
    BasisMlirProgram,
    BasisMlirStruct,
)
from mlir_dialects.llvm import (
    LlvmMlirBlock,
    LlvmMlirExtern,
    LlvmMlirFunction,
    LlvmMlirGlobal,
    LlvmMlirModule,
    LlvmMlirOp,
    LlvmMlirParam,
    LlvmMlirProgram,
    LlvmMlirTypeDecl,
)


class BasisToLlvmLoweringError(ValueError):
    """Raised when a BASIS dialect op is not yet legalizable for the Phase 6 pipeline."""


def convert_basis_to_llvm_mlir(program: BasisMlirProgram) -> LlvmMlirProgram:
    return LlvmMlirProgram(
        name=program.name,
        target=program.target,
        profile=program.profile,
        entry=program.entry,
        attrs={
            "basis.target": json.dumps(program.target),
            "basis.profile": json.dumps(program.profile),
            "basis.entry": json.dumps(program.entry),
            "phase": json.dumps("phase6-llvm-lowered"),
        },
        modules=[_convert_module(module) for module in program.modules],
    )


def _convert_module(module: BasisMlirModule) -> LlvmMlirModule:
    return LlvmMlirModule(
        name=module.name,
        attrs=dict(module.attrs),
        type_decls=[_convert_struct_type(struct_def) for struct_def in module.structs],
        globals=[_convert_global(global_value) for global_value in module.globals],
        externs=[_convert_extern(extern_fn) for extern_fn in module.externs],
        functions=[_convert_function(function) for function in module.functions],
    )


def _convert_struct_type(struct_def: BasisMlirStruct) -> LlvmMlirTypeDecl:
    field_types = ", ".join(lower_basis_type(field.type_text).llvm for field in struct_def.fields)
    return LlvmMlirTypeDecl(
        name=struct_def.name,
        body=f"!llvm.struct<({field_types})>",
    )


def _convert_global(global_value: BasisMlirGlobal) -> LlvmMlirGlobal:
    lowered_type = lower_basis_type(global_value.type_text)
    return LlvmMlirGlobal(
        name=global_value.name,
        type_text=lowered_type.llvm,
        attrs={"visibility": json.dumps(global_value.visibility)},
        initializer=json.dumps(global_value.initializer) if global_value.initializer is not None else None,
    )


def _convert_extern(extern_fn: BasisMlirExtern) -> LlvmMlirExtern:
    return LlvmMlirExtern(
        name=extern_fn.name,
        params=[
            LlvmMlirParam(name=param.name, type_text=lower_basis_type(param.type_text).llvm)
            for param in extern_fn.params
        ],
        returns=lower_basis_type(extern_fn.returns).llvm,
        attrs=dict(extern_fn.attrs, linkage=json.dumps("external")),
    )


def _convert_function(function: BasisMlirFunction) -> LlvmMlirFunction:
    value_types = _build_value_type_table(function)
    return LlvmMlirFunction(
        name=function.name,
        params=[
            LlvmMlirParam(name=param.name, type_text=lower_basis_type(param.type_text).llvm)
            for param in function.params
        ],
        returns=lower_basis_type(function.returns).llvm,
        attrs=dict(function.attrs),
        blocks=[_convert_block(block, value_types) for block in function.blocks],
    )


def _convert_block(block: BasisMlirBlock, value_types: Dict[str, LoweredTypeInfo]) -> LlvmMlirBlock:
    return LlvmMlirBlock(
        label=block.label,
        ops=[_convert_op(op, value_types) for op in block.ops],
    )


def _convert_op(op: BasisMlirOp, value_types: Dict[str, LoweredTypeInfo]) -> LlvmMlirOp:
    if op.op_name == "basis.br":
        return LlvmMlirOp(op_name="llvm.br", successors=list(op.successors))
    if op.op_name == "basis.cond_br":
        return LlvmMlirOp(op_name="llvm.cond_br", operands=list(op.operands), successors=list(op.successors))
    if op.op_name == "basis.ret":
        lowered_type = lower_basis_type(op.result_type).llvm if op.result_type else None
        return LlvmMlirOp(op_name="llvm.return", operands=list(op.operands), result_type=lowered_type)
    if op.op_name == "basis.unreachable":
        return LlvmMlirOp(op_name="llvm.unreachable")

    result_type = lower_basis_type(op.result_type).llvm if op.result_type else None

    if op.op_name == "basis.call":
        attrs = dict(op.attrs)
        callee = attrs.pop("callee", json.dumps(""))
        attrs["callee"] = callee
        return LlvmMlirOp(
            op_name="llvm.call",
            operands=list(op.operands),
            result=op.result,
            result_type=result_type,
            attrs=attrs,
        )

    if op.op_name == "basis.math":
        return _convert_math_op(op, value_types, result_type)
    if op.op_name == "basis.compare":
        return _convert_compare_op(op, value_types)
    if op.op_name == "basis.cast":
        return LlvmMlirOp(
            op_name="llvm.cast",
            operands=list(op.operands),
            result=op.result,
            result_type=result_type,
            attrs=dict(op.attrs),
        )
    if op.op_name == "basis.load":
        return LlvmMlirOp(
            op_name="llvm.load",
            operands=list(op.operands),
            result=op.result,
            result_type=result_type,
            attrs=dict(op.attrs),
        )
    if op.op_name == "basis.store":
        return LlvmMlirOp(
            op_name="llvm.store",
            operands=list(op.operands),
            attrs=dict(op.attrs),
        )
    if op.op_name == "basis.address_of":
        return LlvmMlirOp(
            op_name="llvm.addressof",
            operands=list(op.operands),
            result=op.result,
            result_type=result_type,
            attrs=dict(op.attrs),
        )
    if op.op_name == "basis.assign":
        return _convert_assign_op(op, result_type)
    if op.op_name == "basis.extract":
        return _convert_extract_op(op, result_type)
    if op.op_name == "basis.insert":
        return _convert_insert_op(op, result_type)
    if op.op_name == "basis.phi":
        raise BasisToLlvmLoweringError("phi nodes are not legalizable in the current Phase 6 pipeline yet")

    raise BasisToLlvmLoweringError(f"unsupported BASIS MLIR op '{op.op_name}' during Phase 6 lowering")


def _convert_math_op(
    op: BasisMlirOp,
    value_types: Dict[str, LoweredTypeInfo],
    result_type: Optional[str],
) -> LlvmMlirOp:
    opcode = json.loads(op.attrs.get("opcode", json.dumps("")))
    type_info = _operand_type_info(op, value_types)
    attrs = dict(op.attrs)
    attrs.pop("opcode", None)

    if len(op.operands) == 1:
        if opcode == "!":
            attrs["predicate"] = json.dumps("eq")
            return LlvmMlirOp(
                "llvm.icmp",
                operands=[op.operands[0], "0"],
                result=op.result,
                result_type="i1",
                attrs=attrs,
            )
        unary_map = {
            "-": "llvm.neg",
            "~": "llvm.not",
        }
        lowered_name = unary_map.get(opcode)
        if lowered_name is None:
            raise BasisToLlvmLoweringError(f"unsupported unary math opcode '{opcode}' in Phase 6")
        return LlvmMlirOp(lowered_name, operands=list(op.operands), result=op.result, result_type=result_type, attrs=attrs)

    binary_map = {
        "+": "llvm.fadd" if type_info.category == "float" else "llvm.add",
        "-": "llvm.fsub" if type_info.category == "float" else "llvm.sub",
        "*": "llvm.fmul" if type_info.category == "float" else "llvm.mul",
        "/": _div_op_name(type_info),
        "%": _rem_op_name(type_info),
        "&": "llvm.and",
        "|": "llvm.or",
        "^": "llvm.xor",
        "<<": "llvm.shl",
        ">>": "llvm.lshr" if type_info.signedness == "unsigned" else "llvm.ashr",
    }
    lowered_name = binary_map.get(opcode)
    if lowered_name is None:
        raise BasisToLlvmLoweringError(f"unsupported binary math opcode '{opcode}' in Phase 6")
    return LlvmMlirOp(
        op_name=lowered_name,
        operands=list(op.operands),
        result=op.result,
        result_type=result_type,
        attrs=attrs,
    )


def _convert_compare_op(op: BasisMlirOp, value_types: Dict[str, LoweredTypeInfo]) -> LlvmMlirOp:
    opcode = json.loads(op.attrs.get("opcode", json.dumps("==")))
    type_info = _operand_type_info(op, value_types)
    attrs = dict(op.attrs)
    attrs.pop("opcode", None)
    if type_info.category == "float":
        predicate_map = {
            "==": "oeq",
            "!=": "one",
            "<": "olt",
            "<=": "ole",
            ">": "ogt",
            ">=": "oge",
        }
        predicate = predicate_map.get(opcode)
        if predicate is None:
            raise BasisToLlvmLoweringError(f"unsupported float compare opcode '{opcode}' in Phase 6")
        attrs["predicate"] = json.dumps(predicate)
        return LlvmMlirOp("llvm.fcmp", operands=list(op.operands), result=op.result, result_type="i1", attrs=attrs)

    predicate_map = {
        "==": "eq",
        "!=": "ne",
        "<": "ult" if type_info.signedness == "unsigned" else "slt",
        "<=": "ule" if type_info.signedness == "unsigned" else "sle",
        ">": "ugt" if type_info.signedness == "unsigned" else "sgt",
        ">=": "uge" if type_info.signedness == "unsigned" else "sge",
    }
    predicate = predicate_map.get(opcode)
    if predicate is None:
        raise BasisToLlvmLoweringError(f"unsupported integer compare opcode '{opcode}' in Phase 6")
    attrs["predicate"] = json.dumps(predicate)
    return LlvmMlirOp("llvm.icmp", operands=list(op.operands), result=op.result, result_type="i1", attrs=attrs)


def _convert_assign_op(op: BasisMlirOp, result_type: Optional[str]) -> LlvmMlirOp:
    opcode = json.loads(op.attrs.get("opcode", json.dumps("")))
    attrs = dict(op.attrs)
    attrs.pop("opcode", None)
    if opcode == "array_literal":
        attrs["aggregate"] = json.dumps("array_zero_init")
        return LlvmMlirOp("llvm.mlir.undef", result=op.result, result_type=result_type, attrs=attrs)
    if opcode == "array_repeat":
        attrs["aggregate"] = json.dumps("array_repeat")
        return LlvmMlirOp(
            "llvm.basis.array_repeat",
            operands=list(op.operands),
            result=op.result,
            result_type=result_type,
            attrs=attrs,
        )
    if opcode.startswith("struct_literal:"):
        attrs["aggregate"] = json.dumps(opcode)
        return LlvmMlirOp("llvm.mlir.undef", result=op.result, result_type=result_type, attrs=attrs)
    raise BasisToLlvmLoweringError(f"unsupported assign opcode '{opcode}' in Phase 6")


def _convert_extract_op(op: BasisMlirOp, result_type: Optional[str]) -> LlvmMlirOp:
    opcode = json.loads(op.attrs.get("opcode", json.dumps("")))
    attrs = dict(op.attrs)
    attrs.pop("opcode", None)
    if opcode == "index":
        attrs["aggregate_index"] = json.dumps("dynamic")
        return LlvmMlirOp(
            "llvm.extractvalue",
            operands=list(op.operands),
            result=op.result,
            result_type=result_type,
            attrs=attrs,
        )
    attrs["field"] = json.dumps(opcode)
    return LlvmMlirOp(
        "llvm.extractvalue",
        operands=list(op.operands),
        result=op.result,
        result_type=result_type,
        attrs=attrs,
    )


def _convert_insert_op(op: BasisMlirOp, result_type: Optional[str]) -> LlvmMlirOp:
    opcode = json.loads(op.attrs.get("opcode", json.dumps("")))
    attrs = dict(op.attrs)
    attrs.pop("opcode", None)
    if opcode == "index":
        attrs["aggregate_index"] = json.dumps("dynamic")
    else:
        attrs["field"] = json.dumps(opcode)
    return LlvmMlirOp(
        "llvm.insertvalue",
        operands=list(op.operands),
        result=op.result,
        result_type=result_type,
        attrs=attrs,
    )


def _build_value_type_table(function: BasisMlirFunction) -> Dict[str, LoweredTypeInfo]:
    value_types: Dict[str, LoweredTypeInfo] = {}
    for param in function.params:
        value_types[param.name] = lower_basis_type(param.type_text)
    for block in function.blocks:
        for op in block.ops:
            if op.result is not None and op.result_type:
                value_types[op.result] = lower_basis_type(op.result_type)
    return value_types


def _operand_type_info(op: BasisMlirOp, value_types: Dict[str, LoweredTypeInfo]) -> LoweredTypeInfo:
    for operand in op.operands:
        if operand.startswith("%"):
            info = value_types.get(operand[1:])
            if info is not None:
                return info
        else:
            if operand in {"true", "false"}:
                return LoweredTypeInfo(original="i1", llvm="i1", category="bool")
            if "." in operand:
                return LoweredTypeInfo(original="f64", llvm="f64", category="float", bit_width=64)
            if operand.startswith('"'):
                return LoweredTypeInfo(original="!basis.ptr<i8>", llvm="!llvm.ptr<i8>", category="pointer")
    if op.result_type:
        return lower_basis_type(op.result_type)
    raise BasisToLlvmLoweringError(f"unable to infer operand type for op '{op.op_name}'")


def _div_op_name(type_info: LoweredTypeInfo) -> str:
    if type_info.category == "float":
        return "llvm.fdiv"
    return "llvm.udiv" if type_info.signedness == "unsigned" else "llvm.sdiv"


def _rem_op_name(type_info: LoweredTypeInfo) -> str:
    if type_info.category == "float":
        return "llvm.frem"
    return "llvm.urem" if type_info.signedness == "unsigned" else "llvm.srem"
