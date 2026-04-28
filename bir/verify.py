"""
Phase 1 BIR verification.

The verifier enforces structural and semantic invariants that must hold before
any backend-specific lowering is allowed.
"""

from typing import Dict, List, Set

from bir.model import (
    Block,
    Extern,
    Function,
    Program,
    StructDef,
    SymbolRef,
    Terminator,
    Type,
)


class BirVerificationError(ValueError):
    """Raised when a BIR invariant is violated."""


_VALID_PROFILES = {"strict", "relaxed"}
_VALID_VISIBILITIES = {"public", "private", "entry"}
_VALID_INSTRUCTION_KINDS = {
    "assign",
    "call",
    "load",
    "store",
    "cast",
    "phi",
    "compare",
    "math",
    "address_of",
    "extract",
    "insert",
}
_VALID_TERMINATORS = {"ret", "br", "cond_br", "unreachable"}
_VALID_TYPE_KINDS = {
    "i8",
    "i16",
    "i32",
    "i64",
    "u8",
    "u16",
    "u32",
    "u64",
    "bool",
    "f32",
    "f64",
    "ptr",
    "array",
    "struct",
    "void",
}


def verify_program(program: Program):
    if not program.name:
        raise BirVerificationError("program.name must be non-empty")
    if not program.target:
        raise BirVerificationError("program.target must be non-empty")
    if program.profile not in _VALID_PROFILES:
        raise BirVerificationError(f"program.profile must be one of {_VALID_PROFILES}")
    if not program.modules:
        raise BirVerificationError("program must contain at least one module")

    module_names: Set[str] = set()
    function_table: Dict[str, Function] = {}

    for module in program.modules:
        if not module.name:
            raise BirVerificationError("module.name must be non-empty")
        if module.name in module_names:
            raise BirVerificationError(f"duplicate module '{module.name}'")
        module_names.add(module.name)

        if module.attrs.max_memory < 0:
            raise BirVerificationError(f"module '{module.name}' max_memory must be non-negative")
        if module.resources.stack_max < 0 or module.resources.heap_max < 0:
            raise BirVerificationError(f"module '{module.name}' resources must be non-negative")
        if module.resources.storage_max < 0 or module.resources.code_size_estimate < 0:
            raise BirVerificationError(f"module '{module.name}' resource estimates must be non-negative")

        local_symbols: Set[str] = set()
        struct_names: Set[str] = set()
        for struct_def in module.structs:
            verify_struct(module.name, struct_def)
            if struct_def.name in struct_names:
                raise BirVerificationError(f"duplicate struct '{module.name}::{struct_def.name}'")
            struct_names.add(struct_def.name)

        for function in module.functions:
            verify_function(module.name, function)
            if function.name in local_symbols:
                raise BirVerificationError(f"duplicate symbol '{module.name}::{function.name}'")
            local_symbols.add(function.name)
            function_table[f"{module.name}::{function.name}"] = function

        for extern in module.externs:
            verify_extern(module.name, extern)
            if extern.name in local_symbols:
                raise BirVerificationError(f"duplicate symbol '{module.name}::{extern.name}'")
            local_symbols.add(extern.name)

    entry_name = program.entry.qualified_name()
    entry_function = function_table.get(entry_name)
    if entry_function is None:
        raise BirVerificationError(f"program entry '{entry_name}' does not resolve to a function body")
    if entry_function.visibility != "entry":
        raise BirVerificationError(f"program entry '{entry_name}' must have visibility='entry'")


def verify_function(module_name: str, function: Function):
    if not function.name:
        raise BirVerificationError(f"function in module '{module_name}' must have a name")
    if function.visibility not in _VALID_VISIBILITIES:
        raise BirVerificationError(f"function '{module_name}::{function.name}' has invalid visibility")
    verify_type(function.returns, f"function '{module_name}::{function.name}' return type")

    if function.resources.stack_max is not None and function.resources.stack_max < 0:
        raise BirVerificationError(f"function '{module_name}::{function.name}' stack_max must be non-negative")
    if function.resources.heap_max is not None and function.resources.heap_max < 0:
        raise BirVerificationError(f"function '{module_name}::{function.name}' heap_max must be non-negative")

    if function.attrs.recursion_max is not None and function.attrs.recursion_max <= 0:
        raise BirVerificationError(f"function '{module_name}::{function.name}' recursion_max must be positive")
    if function.attrs.task_stack is not None and function.attrs.task_stack <= 0:
        raise BirVerificationError(f"function '{module_name}::{function.name}' task_stack must be positive")
    if function.attrs.allocates_max is not None and function.attrs.allocates_max < 0:
        raise BirVerificationError(f"function '{module_name}::{function.name}' allocates_max must be non-negative")

    if not function.blocks:
        raise BirVerificationError(f"function '{module_name}::{function.name}' must contain explicit blocks")

    block_names: Set[str] = set()
    value_names: Set[str] = {param.name for param in function.params}
    for param in function.params:
        verify_type(param.type, f"function '{module_name}::{function.name}' param '{param.name}'")

    for block in function.blocks:
        verify_block(module_name, function.name, block)
        if block.name in block_names:
            raise BirVerificationError(f"function '{module_name}::{function.name}' has duplicate block '{block.name}'")
        block_names.add(block.name)

        for instruction in block.instructions:
            if instruction.kind not in _VALID_INSTRUCTION_KINDS:
                raise BirVerificationError(
                    f"function '{module_name}::{function.name}' has invalid instruction kind '{instruction.kind}'"
                )
            verify_type(instruction.type, f"instruction in '{module_name}::{function.name}'")
            if instruction.result is not None:
                if instruction.result.name in value_names:
                    raise BirVerificationError(
                        f"function '{module_name}::{function.name}' redefines value '{instruction.result.name}'"
                    )
                value_names.add(instruction.result.name)

    verify_control_flow(module_name, function.name, function.blocks)


def verify_extern(module_name: str, extern: Extern):
    if not extern.name:
        raise BirVerificationError(f"extern in module '{module_name}' must have a name")
    if extern.visibility not in _VALID_VISIBILITIES:
        raise BirVerificationError(f"extern '{module_name}::{extern.name}' has invalid visibility")
    if not extern.abi:
        raise BirVerificationError(f"extern '{module_name}::{extern.name}' must declare an ABI")
    if extern.resources.stack_max is None or extern.resources.stack_max <= 0:
        raise BirVerificationError(f"extern '{module_name}::{extern.name}' must carry stack_max metadata")
    verify_type(extern.returns, f"extern '{module_name}::{extern.name}' return type")
    for param in extern.params:
        verify_type(param.type, f"extern '{module_name}::{extern.name}' param '{param.name}'")


def verify_struct(module_name: str, struct_def: StructDef):
    if not struct_def.name:
        raise BirVerificationError(f"struct in module '{module_name}' must have a name")
    if struct_def.visibility not in _VALID_VISIBILITIES:
        raise BirVerificationError(f"struct '{module_name}::{struct_def.name}' has invalid visibility")
    if not struct_def.fields:
        raise BirVerificationError(f"struct '{module_name}::{struct_def.name}' must contain fields")

    field_names: Set[str] = set()
    for field in struct_def.fields:
        if field.name in field_names:
            raise BirVerificationError(f"struct '{module_name}::{struct_def.name}' has duplicate field '{field.name}'")
        field_names.add(field.name)
        verify_type(field.type, f"struct '{module_name}::{struct_def.name}' field '{field.name}'")


def verify_block(module_name: str, function_name: str, block: Block):
    if not block.name:
        raise BirVerificationError(f"function '{module_name}::{function_name}' contains unnamed block")
    verify_terminator(module_name, function_name, block.terminator)


def verify_terminator(module_name: str, function_name: str, terminator: Terminator):
    if terminator.kind not in _VALID_TERMINATORS:
        raise BirVerificationError(
            f"function '{module_name}::{function_name}' has invalid terminator kind '{terminator.kind}'"
        )
    if terminator.kind == "br" and len(terminator.targets) != 1:
        raise BirVerificationError(f"function '{module_name}::{function_name}' br terminator must have one target")
    if terminator.kind == "cond_br" and len(terminator.targets) != 2:
        raise BirVerificationError(
            f"function '{module_name}::{function_name}' cond_br terminator must have two targets"
        )
    if terminator.kind == "ret" and terminator.targets:
        raise BirVerificationError(f"function '{module_name}::{function_name}' ret terminator cannot target blocks")
    if terminator.kind == "unreachable" and (terminator.targets or terminator.operands):
        raise BirVerificationError(
            f"function '{module_name}::{function_name}' unreachable terminator must be empty"
        )


def verify_type(type_node: Type, context: str):
    if type_node.kind not in _VALID_TYPE_KINDS:
        raise BirVerificationError(f"{context} uses invalid type kind '{type_node.kind}'")
    if type_node.volatile and type_node.kind != "ptr":
        raise BirVerificationError(f"{context} only pointer types may be volatile")

    if type_node.kind == "ptr":
        if type_node.elem is None:
            raise BirVerificationError(f"{context} pointer type must include elem")
        verify_type(type_node.elem, context)
        if type_node.fields or type_node.len is not None:
            raise BirVerificationError(f"{context} pointer type cannot carry array/struct payload")

    if type_node.kind == "array":
        if type_node.elem is None or type_node.len is None:
            raise BirVerificationError(f"{context} array type must include elem and len")
        if type_node.len <= 0:
            raise BirVerificationError(f"{context} array length must be positive")
        verify_type(type_node.elem, context)
        if type_node.volatile:
            raise BirVerificationError(f"{context} only pointer types may be volatile")

    if type_node.kind == "struct":
        if not type_node.name:
            raise BirVerificationError(f"{context} struct type must include a name")
        if not type_node.fields:
            raise BirVerificationError(f"{context} struct type must include fields")
        field_names: Set[str] = set()
        for field in type_node.fields:
            if field.name in field_names:
                raise BirVerificationError(f"{context} struct type has duplicate field '{field.name}'")
            field_names.add(field.name)
            verify_type(field.type, context)
        if type_node.volatile:
            raise BirVerificationError(f"{context} only pointer types may be volatile")

    if type_node.kind == "void" and (type_node.elem is not None or type_node.len is not None or type_node.fields):
        raise BirVerificationError(f"{context} void type cannot carry extra shape")
    if type_node.kind == "void" and (type_node.name is not None or type_node.volatile):
        raise BirVerificationError(f"{context} void type cannot carry qualifiers or names")


def verify_control_flow(module_name: str, function_name: str, blocks: List[Block]):
    known_blocks = {block.name for block in blocks}
    for block in blocks:
        for target in block.terminator.targets:
            if target not in known_blocks:
                raise BirVerificationError(
                    f"function '{module_name}::{function_name}' targets unknown block '{target}'"
                )
