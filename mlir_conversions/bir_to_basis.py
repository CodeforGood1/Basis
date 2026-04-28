"""
Lower validated BIR into the textual BASIS MLIR dialect model.
"""

import base64
import json
from typing import Dict, List

from bir.model import Block, Extern, Function, Global, Import, Instruction, Module, Program, Terminator, Type, ValueRef
from mlir_dialects.basis import (
    BasisMlirBlock,
    BasisMlirExtern,
    BasisMlirField,
    BasisMlirFunction,
    BasisMlirGlobal,
    BasisMlirImport,
    BasisMlirModule,
    BasisMlirOp,
    BasisMlirProgram,
    BasisMlirStruct,
    render_basis_type,
)
from mlir_dialects.control import render_control_attr
from mlir_dialects.extern import render_effects_attr, render_extern_attr
from mlir_dialects.isr import render_execution_attr
from mlir_dialects.mem import render_memory_attr, render_pointer_qualifier_attr
from mlir_dialects.resource import render_resource_attr


def convert_program_to_basis_mlir(program: Program, *, export_all: bool = False) -> BasisMlirProgram:
    module_symbols = {module.name: module for module in program.modules}
    return BasisMlirProgram(
        name=program.name,
        target=program.target,
        profile=program.profile,
        entry=program.entry.qualified_name(),
        attrs={
            "basis.target": json.dumps(program.target),
            "basis.profile": json.dumps(program.profile),
            "basis.entry": json.dumps(program.entry.qualified_name()),
        },
        modules=[_convert_module(module, module_symbols, export_all=export_all) for module in program.modules],
    )


def _convert_module(module: Module, module_symbols: Dict[str, Module], *, export_all: bool) -> BasisMlirModule:
    return BasisMlirModule(
        name=module.name,
        source_path=module.source_path,
        attrs={
            "basis.source_path": json.dumps(module.source_path),
            "basis.max_memory": str(module.attrs.max_memory),
            "basis.max_storage": "none" if module.attrs.max_storage is None else str(module.attrs.max_storage),
            "basis.max_storage_objects": (
                "none" if module.attrs.max_storage_objects is None else str(module.attrs.max_storage_objects)
            ),
            "basis.strict": str(module.attrs.strict).lower(),
            "basis.resources": render_resource_attr(
                stack_max=module.resources.stack_max,
                heap_max=module.resources.heap_max,
                storage_max=module.resources.storage_max,
                code_size_estimate=module.resources.code_size_estimate,
                deepest_call_path=[ref.qualified_name() for ref in module.resources.deepest_call_path],
            ),
        },
        imports=[_convert_import(import_decl) for import_decl in module.imports],
        structs=[
            BasisMlirStruct(
                name=struct_def.name,
                visibility=_effective_visibility(struct_def.visibility, export_all),
                fields=[BasisMlirField(name=field.name, type_text=render_basis_type(field.type)) for field in struct_def.fields],
            )
            for struct_def in module.structs
        ],
        globals=[_convert_global(global_value, export_all=export_all) for global_value in module.globals],
        externs=[_convert_extern(extern_fn, export_all=export_all) for extern_fn in module.externs],
        functions=[
            _convert_function(function, module, module_symbols, export_all=export_all) for function in module.functions
        ],
    )


def _convert_import(import_decl: Import) -> BasisMlirImport:
    return BasisMlirImport(
        module_name=import_decl.module_name,
        items=list(import_decl.items),
        is_wildcard=import_decl.is_wildcard,
    )


def _convert_global(global_value: Global, *, export_all: bool) -> BasisMlirGlobal:
    return BasisMlirGlobal(
        name=global_value.name,
        visibility=_effective_visibility(global_value.visibility, export_all),
        type_text=render_basis_type(global_value.type),
        initializer=global_value.initializer,
    )


def _convert_extern(extern_fn: Extern, *, export_all: bool) -> BasisMlirExtern:
    return BasisMlirExtern(
        name=extern_fn.name,
        visibility=_effective_visibility(extern_fn.visibility, export_all),
        params=[BasisMlirField(name=param.name, type_text=render_basis_type(param.type)) for param in extern_fn.params],
        returns=render_basis_type(extern_fn.returns),
        attrs=_build_callable_attrs(
            visibility=_effective_visibility(extern_fn.visibility, export_all),
            recursion_max=extern_fn.attrs.recursion_max,
            deterministic=extern_fn.effects.deterministic,
            blocking=extern_fn.effects.blocking,
            allocates=extern_fn.effects.allocates,
            uses_storage=extern_fn.effects.uses_storage,
            isr_safe=extern_fn.effects.isr_safe,
            stack_max=extern_fn.resources.stack_max,
            heap_max=extern_fn.resources.heap_max,
            interrupt=extern_fn.attrs.interrupt,
            task_stack=extern_fn.attrs.task_stack,
            task_priority=extern_fn.attrs.task_priority,
            region_name=extern_fn.attrs.region_name,
            inline_hint=extern_fn.attrs.inline_hint,
            reentrant=extern_fn.attrs.reentrant,
            uses_timer=extern_fn.attrs.uses_timer,
            may_fail=extern_fn.attrs.may_fail,
            allocates_max=extern_fn.attrs.allocates_max,
            storage_bytes=extern_fn.attrs.storage_bytes,
            storage_objects=extern_fn.attrs.storage_objects,
            block_count=0,
            extern_abi=extern_fn.abi,
            extern_symbol_name=extern_fn.symbol_name,
        ),
    )


def _convert_function(
    function: Function,
    module: Module,
    module_symbols: Dict[str, Module],
    *,
    export_all: bool,
) -> BasisMlirFunction:
    value_types = _build_value_type_table(module, function)
    return BasisMlirFunction(
        name=function.name,
        visibility=_effective_visibility(function.visibility, export_all),
        params=[BasisMlirField(name=param.name, type_text=render_basis_type(param.type)) for param in function.params],
        returns=render_basis_type(function.returns),
        attrs=_build_callable_attrs(
            visibility=_effective_visibility(function.visibility, export_all),
            recursion_max=function.attrs.recursion_max,
            deterministic=function.effects.deterministic,
            blocking=function.effects.blocking,
            allocates=function.effects.allocates,
            uses_storage=function.effects.uses_storage,
            isr_safe=function.effects.isr_safe,
            stack_max=function.resources.stack_max,
            heap_max=function.resources.heap_max,
            interrupt=function.attrs.interrupt,
            task_stack=function.attrs.task_stack,
            task_priority=function.attrs.task_priority,
            region_name=function.attrs.region_name,
            inline_hint=function.attrs.inline_hint,
            reentrant=function.attrs.reentrant,
            uses_timer=function.attrs.uses_timer,
            may_fail=function.attrs.may_fail,
            allocates_max=function.attrs.allocates_max,
            storage_bytes=function.attrs.storage_bytes,
            storage_objects=function.attrs.storage_objects,
            block_count=len(function.blocks),
        ),
        blocks=[_convert_block(block, value_types) for block in function.blocks],
    )


def _convert_block(block: Block, value_types: Dict[str, Type]) -> BasisMlirBlock:
    ops = [_convert_instruction(instruction, value_types) for instruction in block.instructions]
    ops.append(_convert_terminator(block.terminator, value_types))
    return BasisMlirBlock(label=block.name, ops=ops)


def _convert_instruction(instruction: Instruction, value_types: Dict[str, Type]) -> BasisMlirOp:
    attrs = _build_instruction_attrs(instruction, value_types)
    operands = []
    op_name = f"basis.{instruction.kind}"

    if instruction.kind == "call":
        attrs["callee"] = json.dumps(instruction.opcode or "")
        operands = [_render_value(operand) for operand in instruction.operands[1:]]
    else:
        operands = [_render_value(operand) for operand in instruction.operands]

    return BasisMlirOp(
        op_name=op_name,
        operands=operands,
        result=instruction.result.name if instruction.result is not None else None,
        result_type=render_basis_type(instruction.type),
        attrs=attrs,
    )


def _convert_terminator(terminator: Terminator, value_types: Dict[str, Type]) -> BasisMlirOp:
    if terminator.kind == "ret":
        result_type = None
        operands = [_render_value(operand) for operand in terminator.operands]
        if terminator.operands:
            operand_type = value_types.get(terminator.operands[0].name)
            if operand_type is not None:
                result_type = render_basis_type(operand_type)
        return BasisMlirOp(op_name="basis.ret", operands=operands, result_type=result_type)
    if terminator.kind == "br":
        return BasisMlirOp(op_name="basis.br", successors=list(terminator.targets))
    if terminator.kind == "cond_br":
        return BasisMlirOp(
            op_name="basis.cond_br",
            operands=[_render_value(terminator.operands[0])],
            successors=list(terminator.targets),
        )
    return BasisMlirOp(op_name="basis.unreachable")


def _build_callable_attrs(
    *,
    visibility: str,
    recursion_max,
    deterministic: bool,
    blocking: bool,
    allocates,
    uses_storage: bool,
    isr_safe: bool,
    stack_max,
    heap_max,
    interrupt: bool,
    task_stack,
    task_priority,
    region_name,
    inline_hint: bool,
    reentrant,
    uses_timer: bool,
    may_fail: bool,
    allocates_max,
    storage_bytes,
    storage_objects,
    block_count: int,
    extern_abi=None,
    extern_symbol_name=None,
) -> Dict[str, str]:
    attrs = {
        "visibility": json.dumps(visibility),
        "basis.effects": render_effects_attr(
            deterministic=deterministic,
            blocking=blocking,
            allocates=allocates,
            uses_storage=uses_storage,
            isr_safe=isr_safe,
        ),
        "basis.resources": render_resource_attr(stack_max=stack_max, heap_max=heap_max),
        "basis.control": render_control_attr(recursion_max=recursion_max, block_count=block_count),
        "basis.mem": render_memory_attr(
            allocates_max=allocates_max,
            storage_bytes=storage_bytes,
            storage_objects=storage_objects,
        ),
        "basis.isr": render_execution_attr(
            interrupt=interrupt,
            task_stack=task_stack,
            task_priority=task_priority,
            region_name=region_name,
            inline_hint=inline_hint,
            reentrant=reentrant,
            uses_timer=uses_timer,
            may_fail=may_fail,
        ),
    }
    if extern_abi is not None:
        attrs["basis.extern"] = render_extern_attr(abi=extern_abi, symbol_name=extern_symbol_name)
    return attrs


def _build_instruction_attrs(instruction: Instruction, value_types: Dict[str, Type]) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    if instruction.opcode is not None:
        attrs["opcode"] = json.dumps(instruction.opcode)
    if instruction.metadata.source_loc is not None:
        loc = instruction.metadata.source_loc
        attrs["source_loc"] = json.dumps(f"{loc.path}:{loc.line}:{loc.column}")
    if instruction.metadata.effect_notes:
        attrs["effect_notes"] = "[" + ", ".join(json.dumps(item) for item in instruction.metadata.effect_notes) + "]"
    if instruction.metadata.resource_notes:
        attrs["resource_notes"] = (
            "[" + ", ".join(json.dumps(item) for item in instruction.metadata.resource_notes) + "]"
        )
    if instruction.type.kind == "ptr":
        attrs["basis.pointer"] = render_pointer_qualifier_attr(is_volatile=instruction.type.volatile)
    for operand in instruction.operands:
        operand_type = value_types.get(operand.name)
        if operand_type is not None and operand_type.kind == "ptr":
            attrs.setdefault("basis.pointer", render_pointer_qualifier_attr(is_volatile=operand_type.volatile))
            break
    return attrs


def _build_value_type_table(module: Module, function: Function) -> Dict[str, Type]:
    value_types: Dict[str, Type] = {}
    for param in function.params:
        value_types[param.name] = param.type
    for global_value in module.globals:
        value_types[global_value.name] = global_value.type
    for extern_fn in module.externs:
        value_types[extern_fn.name] = extern_fn.returns
    for block in function.blocks:
        for instruction in block.instructions:
            if instruction.result is not None:
                value_types[instruction.result.name] = instruction.type
            if instruction.kind in {"store", "load"} and instruction.operands:
                target_name = instruction.operands[0].name
                if target_name.startswith("slot_"):
                    value_types.setdefault(target_name, instruction.type)
    return value_types


def _render_value(ref: ValueRef) -> str:
    name = ref.name
    if name.startswith("literal_string_b64_"):
        encoded = name[len("literal_string_b64_") :]
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        return json.dumps(base64.urlsafe_b64decode(encoded + padding).decode("utf-8"))
    if name.startswith("literal_"):
        _, literal_kind, raw_value = name.split("_", 2)
        value_text = raw_value.replace("neg_", "-")
        if literal_kind == "bool":
            return "true" if raw_value == "true" else "false"
        if literal_kind in {"int", "float"} or literal_kind.startswith(("i", "u", "f")):
            return value_text
    if name == "void":
        return "%void"
    return f"%{name}"


def _effective_visibility(visibility: str, export_all: bool) -> str:
    if export_all and visibility == "private":
        return "public"
    return visibility
