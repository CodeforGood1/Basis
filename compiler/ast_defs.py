"""
BASIS Abstract Syntax Tree (AST) Node Definitions
Pure data structures representing the syntax of BASIS programs.
No parsing logic, no semantic analysis.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ============================================================================
# Utility Functions
# ============================================================================

def parse_int_literal(value: str) -> int:
    """Parse an integer literal string, handling hex (0x), binary (0b), and decimal."""
    if value.startswith('0x') or value.startswith('0X'):
        return int(value, 16)
    elif value.startswith('0b') or value.startswith('0B'):
        return int(value, 2)
    else:
        return int(value)


# ============================================================================
# Source Location
# ============================================================================

@dataclass
class SourceSpan:
    """Represents a range in source code."""
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    
    def __repr__(self):
        if self.start_line == self.end_line:
            return f"{self.start_line}:{self.start_col}-{self.end_col}"
        return f"{self.start_line}:{self.start_col}-{self.end_line}:{self.end_col}"


# ============================================================================
# Base AST Node
# ============================================================================

@dataclass
class ASTNode:
    """Base class for all AST nodes."""
    span: SourceSpan


# ============================================================================
# Module (Top-level)
# ============================================================================

@dataclass
class Module(ASTNode):
    """Top-level module containing declarations."""
    name: str  # Module name (from filename)
    declarations: List['Declaration']
    max_memory_bytes: Optional[int] = None  # max_memory directive (required for main files)
    directives: Dict[str, object] = field(default_factory=dict)


# ============================================================================
# Declarations
# ============================================================================

@dataclass
class Declaration(ASTNode):
    """Base class for all declarations."""
    pass


@dataclass
class Param(ASTNode):
    """Function parameter."""
    name: str
    type: 'Type'


@dataclass
class FunctionDecl(Declaration):
    """Function declaration."""
    name: str
    params: List[Param]
    return_type: 'Type'
    body: Optional['Block']  # None for extern functions
    is_extern: bool
    visibility: Optional[str]  # 'public', 'private', or None
    annotations: List['Annotation']
    extern_symbol: Optional[str]  # For extern fn foo() = "bar";


@dataclass
class StructField(ASTNode):
    """Struct field declaration."""
    name: str
    type: 'Type'


@dataclass
class StructDecl(Declaration):
    """Struct declaration."""
    name: str
    fields: List[StructField]
    visibility: Optional[str]  # 'public', 'private', or None
    annotations: List['Annotation'] = field(default_factory=list)


@dataclass
class ConstDecl(Declaration):
    """Const (immutable constant) declaration."""
    name: str
    type: 'Type'
    value: 'Expression'
    visibility: Optional[str]


@dataclass
class ImportDecl(Declaration):
    """Import declaration."""
    module_name: str
    items: Optional[List[str]]  # None for import mod; list for import mod::{a,b}
    is_wildcard: bool  # True for import mod::*


@dataclass
class ExternStaticDecl(Declaration):
    """Extern static declaration."""
    name: str
    type: 'Type'


# ============================================================================
# Annotations
# ============================================================================

@dataclass
class Annotation(ASTNode):
    """Function or struct annotation like @stack(256) or @recursion(max=10)."""
    name: str  # e.g., "stack", "inline", "recursion", "align"
    arguments: Optional[Dict[str, 'Expression']] = field(default_factory=dict)


# ============================================================================
# Types
# ============================================================================

@dataclass
class Type(ASTNode):
    """Base class for type nodes."""
    pass


@dataclass
class TypeName(Type):
    """Named type (e.g., i32, Point)."""
    name: str


@dataclass
class PointerType(Type):
    """Pointer type (*T)."""
    base_type: Type


@dataclass
class ArrayType(Type):
    """Fixed-size array type ([T; N])."""
    element_type: Type
    size_expr: 'Expression'


@dataclass
class VolatileType(Type):
    """Volatile pointer type (volatile *T) for memory-mapped I/O registers."""
    base_type: Type


# ============================================================================
# Statements
# ============================================================================

@dataclass
class Statement(ASTNode):
    """Base class for statements."""
    pass


@dataclass
class Block(Statement):
    """Block of statements { ... }."""
    statements: List[Statement]


@dataclass
class ReturnStmt(Statement):
    """Return statement."""
    value: Optional['Expression']


@dataclass
class IfStmt(Statement):
    """If statement with optional elif and else branches."""
    condition: 'Expression'
    then_block: Block
    elif_branches: List['ElifBranch']
    else_block: Optional[Block]


@dataclass
class ElifBranch(ASTNode):
    """Elif branch in an if statement."""
    condition: 'Expression'
    block: Block


@dataclass
class ForStmt(Statement):
    """For loop: for var in start..end { }."""
    iterator_name: str
    range_start: 'Expression'
    range_end: 'Expression'
    body: Block


@dataclass
class WhileStmt(Statement):
    """While loop: while condition { }."""
    condition: 'Expression'
    body: Block
    max_iterations: Optional[int] = None  # From @bounded annotation or analysis


@dataclass
class BreakStmt(Statement):
    """Break statement."""
    pass


@dataclass
class ContinueStmt(Statement):
    """Continue statement."""
    pass


@dataclass
class ExprStmt(Statement):
    """Expression statement."""
    expression: 'Expression'


@dataclass
class LetDecl(Declaration, Statement):
    """Let (mutable variable) declaration."""
    name: str
    type: 'Type'
    initializer: Optional['Expression']


# ============================================================================
# Expressions
# ============================================================================

@dataclass
class Expression(ASTNode):
    """Base class for expressions."""
    pass


@dataclass
class IdentifierExpr(Expression):
    """Identifier reference."""
    name: str


@dataclass
class LiteralExpr(Expression):
    """Literal value."""
    value: str  # Raw lexeme
    kind: str   # 'int', 'float', 'string', 'bool'


@dataclass
class BinaryExpr(Expression):
    """Binary operation."""
    left: Expression
    operator: str
    right: Expression


@dataclass
class UnaryExpr(Expression):
    """Unary operation."""
    operator: str
    operand: Expression


@dataclass
class CallExpr(Expression):
    """Function call."""
    callee: Expression
    arguments: List[Expression]


@dataclass
class IndexExpr(Expression):
    """Array/pointer indexing: base[index]."""
    base: Expression
    index: Expression
    # Populated during typecheck for runtime bounds checking
    array_size: Optional[int] = None


@dataclass
class FieldAccessExpr(Expression):
    """Struct field access: base.field."""
    base: Expression
    field_name: str
    base_is_pointer: bool = False


@dataclass
class AssignmentExpr(Expression):
    """Assignment: target = value."""
    target: Expression
    operator: str  # '=', '+=', '-=', etc.
    value: Expression


@dataclass
class CastExpr(Expression):
    """Type cast."""
    expression: Expression
    target_type: Type


@dataclass
class AddressOfExpr(Expression):
    """Address-of operator: &expr."""
    operand: Expression


@dataclass
class DereferenceExpr(Expression):
    """Dereference operator: *expr."""
    operand: Expression


@dataclass
class ArrayLiteralExpr(Expression):
    """Array literal: [expr1, expr2, ...]."""
    elements: List[Expression]


@dataclass
class ArrayRepeatExpr(Expression):
    """Array repeat initialization: [value; count] or [value; count | idx: val, ...]."""
    value: Expression              # Default value for all elements
    count: Expression              # Number of elements (must be compile-time constant)
    overrides: List['ArrayOverride']  # Optional sparse overrides


@dataclass
class ArrayOverride(ASTNode):
    """Override for specific index in array repeat: index: value."""
    index: Expression
    value: Expression


@dataclass
class StructLiteralExpr(Expression):
    """Struct literal: StructName { field1: value1, field2: value2, ... }."""
    struct_name: str
    field_inits: List['FieldInit']  # List of (field_name, value) pairs


@dataclass
class FieldInit(ASTNode):
    """Field initialization in struct literal."""
    field_name: str
    value: Expression


# ============================================================================
# AST Printing Utilities
# ============================================================================

def print_ast(node, indent=0):
    """Pretty-print AST for debugging."""
    prefix = "  " * indent
    
    if isinstance(node, Module):
        print(f"{prefix}Module: {node.name}")
        for decl in node.declarations:
            print_ast(decl, indent + 1)
    
    elif isinstance(node, FunctionDecl):
        visibility = f"{node.visibility} " if node.visibility else ""
        extern = "extern " if node.is_extern else ""
        print(f"{prefix}{visibility}{extern}fn {node.name}(")
        for param in node.params:
            print(f"{prefix}  {param.name}: ", end="")
            print_ast_inline(param.type)
        print(f"{prefix}) -> ", end="")
        print_ast_inline(node.return_type)
        if node.annotations:
            print(f" [{', '.join(f'@{a.name}' for a in node.annotations)}]")
        else:
            print()
        if node.body:
            print_ast(node.body, indent + 1)
    
    elif isinstance(node, StructDecl):
        visibility = f"{node.visibility} " if node.visibility else ""
        print(f"{prefix}{visibility}struct {node.name}")
        for field in node.fields:
            print(f"{prefix}  {field.name}: ", end="")
            print_ast_inline(field.type)
            print()
    
    elif isinstance(node, LetDecl):
        print(f"{prefix}let {node.name}: ", end="")
        print_ast_inline(node.type)
        if node.initializer:
            print(" = ", end="")
            print_ast_inline(node.initializer)
        print()
    
    elif isinstance(node, ConstDecl):
        visibility = f"{node.visibility} " if node.visibility else ""
        print(f"{prefix}{visibility}const {node.name}: ", end="")
        print_ast_inline(node.type)
        print(" = ", end="")
        print_ast_inline(node.value)
        print()
    
    elif isinstance(node, ImportDecl):
        if node.is_wildcard:
            print(f"{prefix}import {node.module_name}::*")
        elif node.items:
            items = ", ".join(node.items)
            print(f"{prefix}import {node.module_name}::{{{items}}}")
        else:
            print(f"{prefix}import {node.module_name}")
    
    elif isinstance(node, Block):
        print(f"{prefix}{{")
        for stmt in node.statements:
            print_ast(stmt, indent + 1)
        print(f"{prefix}}}")
    
    elif isinstance(node, ReturnStmt):
        print(f"{prefix}return ", end="")
        if node.value:
            print_ast_inline(node.value)
        print()
    
    elif isinstance(node, IfStmt):
        print(f"{prefix}if ", end="")
        print_ast_inline(node.condition)
        print()
        print_ast(node.then_block, indent + 1)
        for elif_branch in node.elif_branches:
            print(f"{prefix}elif ", end="")
            print_ast_inline(elif_branch.condition)
            print()
            print_ast(elif_branch.block, indent + 1)
        if node.else_block:
            print(f"{prefix}else")
            print_ast(node.else_block, indent + 1)
    
    elif isinstance(node, ForStmt):
        print(f"{prefix}for {node.iterator_name} in ", end="")
        print_ast_inline(node.range_start)
        print("..", end="")
        print_ast_inline(node.range_end)
        print()
        print_ast(node.body, indent + 1)
    
    elif isinstance(node, BreakStmt):
        print(f"{prefix}break")
    
    elif isinstance(node, ContinueStmt):
        print(f"{prefix}continue")
    
    elif isinstance(node, ExprStmt):
        print(f"{prefix}", end="")
        print_ast_inline(node.expression)
        print()
    
    else:
        print(f"{prefix}{node.__class__.__name__}: {node}")


def print_ast_inline(node):
    """Print AST node inline (no newline)."""
    if isinstance(node, TypeName):
        print(node.name, end="")
    elif isinstance(node, PointerType):
        print("*", end="")
        print_ast_inline(node.base_type)
    elif isinstance(node, ArrayType):
        print("[", end="")
        print_ast_inline(node.element_type)
        print("; ", end="")
        print_ast_inline(node.size_expr)
        print("]", end="")
    elif isinstance(node, IdentifierExpr):
        print(node.name, end="")
    elif isinstance(node, LiteralExpr):
        if node.kind == 'string':
            print(f'"{node.value}"', end="")
        else:
            print(node.value, end="")
    elif isinstance(node, BinaryExpr):
        print("(", end="")
        print_ast_inline(node.left)
        print(f" {node.operator} ", end="")
        print_ast_inline(node.right)
        print(")", end="")
    elif isinstance(node, UnaryExpr):
        print(f"({node.operator}", end="")
        print_ast_inline(node.operand)
        print(")", end="")
    elif isinstance(node, CallExpr):
        print_ast_inline(node.callee)
        print("(", end="")
        for i, arg in enumerate(node.arguments):
            if i > 0:
                print(", ", end="")
            print_ast_inline(arg)
        print(")", end="")
    elif isinstance(node, IndexExpr):
        print_ast_inline(node.base)
        print("[", end="")
        print_ast_inline(node.index)
        print("]", end="")
    elif isinstance(node, FieldAccessExpr):
        print_ast_inline(node.base)
        print(f".{node.field_name}", end="")
    elif isinstance(node, AssignmentExpr):
        print_ast_inline(node.target)
        print(f" {node.operator} ", end="")
        print_ast_inline(node.value)
    elif isinstance(node, AddressOfExpr):
        print("(&", end="")
        print_ast_inline(node.operand)
        print(")", end="")
    elif isinstance(node, DereferenceExpr):
        print("(*", end="")
        print_ast_inline(node.operand)
        print(")", end="")
    else:
        print(f"<{node.__class__.__name__}>", end="")
