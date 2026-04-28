"""
Lower the Phase 6 LLVM-dialect-style model into textual LLVM IR.
"""

import json
from typing import Dict, List, Optional, Tuple

from mlir_dialects.llvm import (
    LlvmMlirBlock,
    LlvmMlirExtern,
    LlvmMlirFunction,
    LlvmMlirGlobal,
    LlvmMlirModule,
    LlvmMlirOp,
    LlvmMlirProgram,
)

from .llvm_ir import (
    LlvmIrBlock,
    LlvmIrDeclare,
    LlvmIrFunction,
    LlvmIrGlobal,
    LlvmIrInstruction,
    LlvmIrModule,
)


class LlvmIrLoweringError(ValueError):
    """Raised when the Phase 6 model cannot be rendered as textual LLVM IR."""


def lower_llvm_mlir_to_ir(program: LlvmMlirProgram) -> LlvmIrModule:
    merged_module = LlvmIrModule(
        source_filename=f"{program.name}.bs",
        target_triple=_target_triple_for(program.target),
    )

    for module in program.modules:
        _merge_module(merged_module, module)
    return merged_module


def _merge_module(target: LlvmIrModule, module: LlvmMlirModule):
    for type_decl in module.type_decls:
        if not type_decl.body.startswith("!llvm.struct<"):
            raise LlvmIrLoweringError(f"unsupported LLVM MLIR type declaration '{type_decl.name}'")
        inner = type_decl.body[len("!llvm.struct<(") : -2]
        target.identified_types[type_decl.name] = "{ " + inner + " }"

    for global_value in module.globals:
        lowered_global = _lower_global(global_value)
        target.globals.append(lowered_global)

    for extern_fn in module.externs:
        target.declarations.append(_lower_extern(extern_fn))

    for function in module.functions:
        target.functions.append(_lower_function(function))


def _lower_global(global_value: LlvmMlirGlobal) -> LlvmIrGlobal:
    initializer = "zeroinitializer"
    is_constant = False
    if global_value.initializer is not None:
        raw_initializer = json.loads(global_value.initializer)
        initializer, is_constant = _lower_global_initializer(global_value.type_text, raw_initializer)
    return LlvmIrGlobal(
        name=global_value.name,
        type_text=global_value.type_text,
        initializer=initializer,
        linkage="internal" if global_value.attrs.get("visibility") == json.dumps("private") else "external",
        is_constant=is_constant,
        align=_preferred_alignment(global_value.type_text),
    )


def _lower_global_initializer(type_text: str, value: str) -> Tuple[str, bool]:
    if type_text == "i1":
        return ("true" if value == "true" else "false"), True
    if type_text.startswith("i") or type_text in {"f32", "f64"}:
        return value, True
    return "zeroinitializer", False


def _lower_extern(extern_fn: LlvmMlirExtern) -> LlvmIrDeclare:
    return LlvmIrDeclare(
        name=extern_fn.name,
        returns=extern_fn.returns,
        params=[param.type_text for param in extern_fn.params],
    )


def _lower_function(function: LlvmMlirFunction) -> LlvmIrFunction:
    value_types = {param.name: param.type_text for param in function.params}
    ir_function = LlvmIrFunction(
        name=function.name,
        returns=function.returns,
        params=[f"{param.type_text} %{param.name}" for param in function.params],
        linkage="internal" if function.attrs.get("visibility") == json.dumps("private") else "dso_local",
        blocks=[],
    )
    for block in function.blocks:
        lowered_block = _lower_block(block, value_types)
        ir_function.blocks.append(lowered_block)
    return ir_function


def _lower_block(block: LlvmMlirBlock, value_types: Dict[str, str]) -> LlvmIrBlock:
    instructions: List[LlvmIrInstruction] = []
    for op in block.ops:
        lowered = _lower_op(op, value_types)
        if op.result and op.result_type:
            value_types[op.result] = op.result_type
        instructions.append(lowered)
    return LlvmIrBlock(label=block.label, instructions=instructions)


def _lower_op(op: LlvmMlirOp, value_types: Dict[str, str]) -> LlvmIrInstruction:
    if op.op_name == "llvm.br":
        return LlvmIrInstruction(result=None, text=f"br label %{op.successors[0]}")
    if op.op_name == "llvm.cond_br":
        return LlvmIrInstruction(
            result=None,
            text=f"br i1 {op.operands[0]}, label %{op.successors[0]}, label %{op.successors[1]}",
        )
    if op.op_name == "llvm.return":
        if not op.operands:
            return LlvmIrInstruction(result=None, text="ret void")
        return LlvmIrInstruction(result=None, text=f"ret {op.result_type} {op.operands[0]}")
    if op.op_name == "llvm.unreachable":
        return LlvmIrInstruction(result=None, text="unreachable")

    if op.result is None:
        return LlvmIrInstruction(result=None, text=_render_instruction(op, value_types))
    return LlvmIrInstruction(result=op.result, text=_render_instruction(op, value_types))


def _render_instruction(op: LlvmMlirOp, value_types: Dict[str, str]) -> str:
    binary_ops = {
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
        "llvm.fadd",
        "llvm.fsub",
        "llvm.fmul",
    }
    if op.op_name in binary_ops:
        return f"{op.op_name[5:]} {op.result_type} {op.operands[0]}, {op.operands[1]}"
    if op.op_name == "llvm.neg":
        return f"sub {op.result_type} 0, {op.operands[0]}"
    if op.op_name == "llvm.not":
        return f"xor {op.result_type} {op.operands[0]}, -1"
    if op.op_name == "llvm.icmp":
        predicate = json.loads(op.attrs.get("predicate", json.dumps("eq")))
        operand_type = _operand_type(op.operands[0], value_types, fallback="i32")
        return f"icmp {predicate} {operand_type} {op.operands[0]}, {op.operands[1]}"
    if op.op_name == "llvm.fcmp":
        predicate = json.loads(op.attrs.get("predicate", json.dumps("oeq")))
        operand_type = _operand_type(op.operands[0], value_types, fallback="f64")
        return f"fcmp {predicate} {operand_type} {op.operands[0]}, {op.operands[1]}"
    if op.op_name == "llvm.call":
        callee = json.loads(op.attrs.get("callee", json.dumps("")))
        arg_text = ", ".join(f"{_operand_type(arg, value_types)} {arg}" for arg in op.operands)
        return f"call {op.result_type} @{callee}({arg_text})"
    if op.op_name == "llvm.load":
        operand_type = _operand_type(op.operands[0], value_types, fallback=op.result_type)
        pointee_type = _pointee_type(operand_type, op.result_type or "i8")
        return f"load {pointee_type}, {operand_type} {op.operands[0]}"
    if op.op_name == "llvm.store":
        value_type = _operand_type(op.operands[1], value_types, fallback="i32")
        pointer_type = _operand_type(op.operands[0], value_types, fallback=f"ptr")
        return f"store {value_type} {op.operands[1]}, {pointer_type} {op.operands[0]}"
    if op.op_name == "llvm.addressof":
        operand_type = _operand_type(op.operands[0], value_types, fallback="ptr")
        return f"bitcast {operand_type} {op.operands[0]} to {op.result_type}"
    if op.op_name == "llvm.extractvalue":
        aggregate_type = _operand_type(op.operands[0], value_types, fallback=op.result_type or "i32")
        if "field" in op.attrs:
            field_name = json.loads(op.attrs["field"])
            return f"extractvalue {aggregate_type} {op.operands[0]}, ; field {field_name}"
        return f"extractvalue {aggregate_type} {op.operands[0]}, ; dynamic index"
    if op.op_name == "llvm.insertvalue":
        aggregate_type = _operand_type(op.operands[0], value_types, fallback=op.result_type or "i32")
        value_type = _operand_type(op.operands[-1], value_types, fallback="i32")
        if "field" in op.attrs:
            field_name = json.loads(op.attrs["field"])
            return f"insertvalue {aggregate_type} {op.operands[0]}, {value_type} {op.operands[-1]}, ; field {field_name}"
        return f"insertvalue {aggregate_type} {op.operands[0]}, {value_type} {op.operands[-1]}, ; dynamic index"
    if op.op_name == "llvm.cast":
        source_type = _operand_type(op.operands[0], value_types, fallback="i32")
        cast_opcode = _select_cast_opcode(source_type, op.result_type or "i32")
        return f"{cast_opcode} {source_type} {op.operands[0]} to {op.result_type}"
    if op.op_name == "llvm.mlir.undef":
        return f"undef ; {json.dumps(op.attrs, sort_keys=True)}"
    if op.op_name == "llvm.basis.array_repeat":
        operand_type = _operand_type(op.operands[0], value_types, fallback="i32")
        return f"call {op.result_type} @__basis_array_repeat({operand_type} {op.operands[0]})"
    raise LlvmIrLoweringError(f"unsupported LLVM MLIR op '{op.op_name}' for LLVM IR emission")


def _operand_type(operand: str, value_types: Dict[str, str], fallback: Optional[str] = None) -> str:
    if operand.startswith("%"):
        return value_types.get(operand[1:], fallback or "i32")
    if operand in {"true", "false"}:
        return "i1"
    if operand.startswith('"'):
        return "ptr"
    if operand.replace("-", "", 1).isdigit():
        return fallback or "i32"
    if "." in operand and all(part.isdigit() for part in operand.replace("-", "", 1).split(".", 1)):
        return fallback or "double"
    return fallback or "i32"


def _pointee_type(pointer_type: str, fallback: str) -> str:
    if pointer_type.startswith("!llvm.ptr<") and pointer_type.endswith(">"):
        return pointer_type[len("!llvm.ptr<") : -1]
    if pointer_type == "ptr":
        return fallback
    return fallback


def _select_cast_opcode(source_type: str, target_type: str) -> str:
    if source_type == target_type:
        return "bitcast"
    if source_type.startswith("!llvm.ptr") and target_type.startswith("!llvm.ptr"):
        return "bitcast"
    if source_type.startswith("!llvm.ptr") and target_type.startswith("i"):
        return "ptrtoint"
    if source_type.startswith("i") and target_type.startswith("!llvm.ptr"):
        return "inttoptr"
    if source_type in {"f32", "f64"} and target_type in {"f32", "f64"}:
        return "fpext" if source_type == "f32" and target_type == "f64" else "fptrunc"
    if source_type.startswith("i") and target_type.startswith("i"):
        source_width = int(source_type[1:])
        target_width = int(target_type[1:])
        if source_width < target_width:
            return "sext"
        if source_width > target_width:
            return "trunc"
        return "bitcast"
    if source_type.startswith("i") and target_type in {"f32", "f64"}:
        return "sitofp"
    if source_type in {"f32", "f64"} and target_type.startswith("i"):
        return "fptosi"
    return "bitcast"


def _preferred_alignment(type_text: str) -> Optional[int]:
    if type_text in {"i1", "i8"}:
        return 1
    if type_text in {"i16"}:
        return 2
    if type_text in {"i32", "f32"}:
        return 4
    if type_text in {"i64", "f64"}:
        return 8
    return None


def _target_triple_for(target_name: str) -> str:
    triples = {
        "host": "unknown-unknown-unknown",
        "esp32": "xtensa-esp32-none-elf",
        "linux": "x86_64-pc-linux-gnu",
    }
    return triples.get(target_name, "unknown-unknown-unknown")
