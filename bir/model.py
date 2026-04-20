"""
BASIS Intermediate Representation (BIR) data model.

Phase 1 keeps BIR intentionally simple:
- typed dataclasses
- explicit blocks and terminators
- frontend-resolved effect/resource metadata
- no backend-specific semantics
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class SourceLoc:
    path: str
    line: int
    column: int
    end_line: Optional[int] = None
    end_column: Optional[int] = None


@dataclass(frozen=True)
class SymbolRef:
    module: str
    name: str

    def qualified_name(self) -> str:
        return f"{self.module}::{self.name}"


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    source_loc: Optional[SourceLoc] = None


@dataclass(frozen=True)
class Import:
    module_name: str
    items: List[str] = field(default_factory=list)
    is_wildcard: bool = False


@dataclass(frozen=True)
class Field:
    name: str
    type: "Type"


@dataclass(frozen=True)
class Type:
    kind: str
    elem: Optional["Type"] = None
    len: Optional[int] = None
    fields: List[Field] = field(default_factory=list)


@dataclass(frozen=True)
class Param:
    name: str
    type: Type


@dataclass(frozen=True)
class ValueRef:
    name: str


@dataclass(frozen=True)
class InstructionMetadata:
    source_loc: Optional[SourceLoc] = None
    effect_notes: List[str] = field(default_factory=list)
    resource_notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Instruction:
    kind: str
    opcode: Optional[str]
    result: Optional[ValueRef]
    operands: List[ValueRef]
    type: Type
    metadata: InstructionMetadata = field(default_factory=InstructionMetadata)


@dataclass(frozen=True)
class Terminator:
    kind: str
    operands: List[ValueRef] = field(default_factory=list)
    targets: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Block:
    name: str
    instructions: List[Instruction]
    terminator: Terminator


@dataclass(frozen=True)
class FunctionAttrs:
    recursion_max: Optional[int] = None
    interrupt: bool = False
    task_stack: Optional[int] = None
    task_priority: Optional[int] = None
    deterministic: Optional[bool] = None
    blocking: bool = False
    allocates_max: Optional[int] = None
    reentrant: Optional[bool] = None
    isr_safe: Optional[bool] = None
    uses_timer: bool = False
    may_fail: bool = False
    storage_bytes: Optional[int] = None
    storage_objects: Optional[int] = None


@dataclass(frozen=True)
class FunctionEffects:
    deterministic: bool
    blocking: bool
    allocates: Optional[int]
    uses_storage: bool
    isr_safe: bool


@dataclass(frozen=True)
class FunctionResources:
    stack_max: Optional[int] = None
    heap_max: Optional[int] = None


@dataclass(frozen=True)
class Function:
    name: str
    visibility: str
    params: List[Param]
    returns: Type
    attrs: FunctionAttrs
    effects: FunctionEffects
    resources: FunctionResources
    blocks: List[Block]


@dataclass(frozen=True)
class Extern:
    name: str
    visibility: str
    params: List[Param]
    returns: Type
    abi: str
    symbol_name: Optional[str]
    attrs: FunctionAttrs
    effects: FunctionEffects
    resources: FunctionResources


@dataclass(frozen=True)
class Global:
    name: str
    visibility: str
    type: Type
    initializer: Optional[str] = None


@dataclass(frozen=True)
class ModuleAttrs:
    max_memory: int
    max_storage: Optional[int] = None
    max_storage_objects: Optional[int] = None
    strict: bool = False


@dataclass(frozen=True)
class ModuleResources:
    stack_max: int
    heap_max: int
    storage_max: int
    code_size_estimate: int
    deepest_call_path: List[SymbolRef] = field(default_factory=list)


@dataclass(frozen=True)
class Module:
    name: str
    source_path: str
    attrs: ModuleAttrs
    imports: List[Import] = field(default_factory=list)
    exports: List[SymbolRef] = field(default_factory=list)
    globals: List[Global] = field(default_factory=list)
    functions: List[Function] = field(default_factory=list)
    externs: List[Extern] = field(default_factory=list)
    resources: ModuleResources = field(
        default_factory=lambda: ModuleResources(
            stack_max=0,
            heap_max=0,
            storage_max=0,
            code_size_estimate=0,
        )
    )


@dataclass(frozen=True)
class Program:
    name: str
    target: str
    profile: str
    entry: SymbolRef
    modules: List[Module]
    diagnostics: List[Diagnostic] = field(default_factory=list)
