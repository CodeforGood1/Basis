"""
BASIS Type Checker
Validates types for all expressions and statements.
Attaches resolved types to expression nodes.
"""

from typing import Dict, Optional
from dataclasses import dataclass
import ast_defs
from ast_defs import (
    SourceSpan, Module, Declaration, FunctionDecl, StructDecl, LetDecl, ConstDecl,
    Param, StructField, ImportDecl, ExternStaticDecl,
    TypeName, Type, Statement, Block, ReturnStmt, IfStmt, ElifBranch, ForStmt, WhileStmt,
    BreakStmt, ContinueStmt, ExprStmt,
    Expression, IdentifierExpr, LiteralExpr, BinaryExpr, UnaryExpr, CallExpr,
    IndexExpr, FieldAccessExpr, AssignmentExpr, CastExpr, AddressOfExpr, DereferenceExpr,
    ArrayLiteralExpr, ArrayRepeatExpr, StructLiteralExpr, FieldInit,
    Annotation, print_ast, print_ast_inline,
    parse_int_literal
)
# Import AST type nodes with ast_defs prefix to avoid conflicts with our runtime type classes
ASTPointerType = ast_defs.PointerType
ASTArrayType = ast_defs.ArrayType
ASTVolatileType = ast_defs.VolatileType
from diagnostics import DiagnosticEngine
from sema import Symbol, Scope


# ============================================================================
# Type Representation
# ============================================================================

@dataclass
class BasisType:
    """Base class for BASIS types."""
    pass


@dataclass
class IntType(BasisType):
    """Integer type (i8, i16, i32, i64, u8, u16, u32, u64)."""
    name: str
    signed: bool
    bits: int
    
    def __eq__(self, other):
        return isinstance(other, IntType) and self.name == other.name


@dataclass
class FloatType(BasisType):
    """Floating point type (f32, f64)."""
    name: str
    bits: int
    
    def __eq__(self, other):
        return isinstance(other, FloatType) and self.name == other.name


@dataclass
class BoolType(BasisType):
    """Boolean type."""
    
    def __eq__(self, other):
        return isinstance(other, BoolType)


@dataclass
class VoidType(BasisType):
    """Void type (only for function returns, not a value type)."""
    
    def __eq__(self, other):
        return isinstance(other, VoidType)


@dataclass
class PointerType(BasisType):
    """Pointer type (*T)."""
    pointee: BasisType
    
    def __eq__(self, other):
        return isinstance(other, PointerType) and self.pointee == other.pointee


@dataclass
class ArrayType(BasisType):
    """Array type ([T; N])."""
    element: BasisType
    size: Optional[int] = None  # None = unknown size
    
    def __eq__(self, other):
        if not isinstance(other, ArrayType):
            return False
        # Element types must match
        if self.element != other.element:
            return False
        # Sizes must match if both are known
        if self.size is not None and other.size is not None:
            return self.size == other.size
        # If either size is None, they're considered compatible
        return True


@dataclass
class StructType(BasisType):
    """Struct type."""
    name: str
    fields: Dict[str, BasisType]
    
    def __eq__(self, other):
        return isinstance(other, StructType) and self.name == other.name


@dataclass
class VolatilePointerType(BasisType):
    """Volatile pointer type for memory-mapped I/O registers."""
    pointee: BasisType
    
    def __eq__(self, other):
        return isinstance(other, VolatilePointerType) and self.pointee == other.pointee


# ============================================================================
# Built-in Types
# ============================================================================

BUILTIN_TYPES = {
    'i8': IntType('i8', True, 8),
    'i16': IntType('i16', True, 16),
    'i32': IntType('i32', True, 32),
    'i64': IntType('i64', True, 64),
    'u8': IntType('u8', False, 8),
    'u16': IntType('u16', False, 16),
    'u32': IntType('u32', False, 32),
    'u64': IntType('u64', False, 64),
    'f32': FloatType('f32', 32),
    'f64': FloatType('f64', 64),
    'bool': BoolType(),
    'void': VoidType(),
}


# ============================================================================
# Type Checker
# ============================================================================

class TypeChecker:
    """
    Type checker for BASIS programs.
    Validates types for all expressions and statements.
    """
    
    def __init__(self, diag_engine: DiagnosticEngine, module_scope: Scope):
        self.diag = diag_engine
        self.module_scope = module_scope
        
        # Current scope stack (rebuilt during type checking)
        self.current_scope: Scope = module_scope
        
        # Type cache: maps expressions to their types
        self.expr_types: Dict[int, BasisType] = {}  # Use id(expr) as key
        
        # Struct definitions
        self.struct_types: Dict[str, StructType] = {}
        
        # Current function return type (for validating return statements)
        self.current_function_return_type: Optional[BasisType] = None
        
        # Current module name
        self.current_module_name: str = ""
    
    # ========================================================================
    # Main Entry Point
    # ========================================================================
    
    def check(self, module: Module) -> bool:
        """
        Type check a module. Returns True if no errors.
        """
        self.current_module_name = module.name
        self.current_scope = self.module_scope
        
        # First pass: collect struct types
        for decl in module.declarations:
            if isinstance(decl, StructDecl):
                self._collect_struct_type(decl)
        
        # Second pass: type check all declarations
        for decl in module.declarations:
            self._check_declaration(decl)
        
        return not self.diag.has_errors()
    
    # ========================================================================
    # Struct Type Collection
    # ========================================================================
    
    def _collect_struct_type(self, decl: StructDecl):
        """Collect a struct type definition."""
        fields = {}
        for field in decl.fields:
            field_type = self._resolve_type(field.type)
            if field_type:
                fields[field.name] = field_type
        
        self.struct_types[decl.name] = StructType(decl.name, fields)
    
    # ========================================================================
    # Type Resolution (AST Type -> BasisType)
    # ========================================================================
    
    def _resolve_type(self, type_node: Type) -> Optional[BasisType]:
        """Convert a type AST node to a BasisType."""
        if isinstance(type_node, TypeName):
            if type_node.name in BUILTIN_TYPES:
                return BUILTIN_TYPES[type_node.name]
            elif type_node.name in self.struct_types:
                return self.struct_types[type_node.name]
            else:
                # Should have been caught by semantic analysis
                return None
        
        elif isinstance(type_node, ASTPointerType):
            base = self._resolve_type(type_node.base_type)
            if base:
                return PointerType(base)
            return None
        
        elif isinstance(type_node, ASTArrayType):
            element = self._resolve_type(type_node.element_type)
            if element:
                # Try to evaluate the size expression
                size = None
                if isinstance(type_node.size_expr, LiteralExpr) and type_node.size_expr.kind == 'int':
                    try:
                        size = parse_int_literal(type_node.size_expr.value)
                    except (ValueError, AttributeError):
                        pass
                # For non-constant sizes, we can't check at compile time
                return ArrayType(element, size)
            return None
        
        elif isinstance(type_node, ASTVolatileType):
            base = self._resolve_type(type_node.base_type)
            if base:
                return VolatilePointerType(base)
            return None
        
        return None
    
    # ========================================================================
    # Declaration Type Checking
    # ========================================================================
    
    def _check_declaration(self, decl: Declaration):
        """Type check a declaration."""
        if isinstance(decl, FunctionDecl):
            self._check_function(decl)
        elif isinstance(decl, ConstDecl):
            self._check_const(decl)
        # Other declarations (struct, import, extern) don't need type checking
    
    def _check_function(self, decl: FunctionDecl):
        """Type check a function declaration."""
        # Resolve return type
        return_type = self._resolve_type(decl.return_type)
        if not return_type:
            return
        
        # Arrays cannot be returned by value (C limitation)
        if isinstance(return_type, ArrayType):
            self._error("E_INVALID_RETURN_TYPE",
                       f"functions cannot return arrays by value; use a pointer or wrap in a struct",
                       decl.return_type.span if hasattr(decl.return_type, 'span') else decl.span)
            return
        
        self.current_function_return_type = return_type
        
        # Create function scope
        func_scope = Scope(parent=self.current_scope, level=1, kind='function')
        prev_scope = self.current_scope
        self.current_scope = func_scope
        
        # Add parameters to function scope (for type lookups)
        for param in decl.params:
            param_type = self._resolve_type(param.type)
            if param_type:
                symbol = Symbol(
                    name=param.name,
                    kind='param',
                    decl_node=param,
                    visibility=None,
                    scope_level=1
                )
                func_scope.define(param.name, symbol)
        
        # Check body if present
        if decl.body:
            self._check_block(decl.body)
            
            # Check that non-void functions return a value on all paths
            if not isinstance(return_type, VoidType):
                if not self._block_always_returns(decl.body):
                    self._error("E_MISSING_RETURN",
                               f"function '{decl.name}' must return a value of type {self._type_to_string(return_type)} on all code paths",
                               decl.span)
        
        self.current_function_return_type = None
        self.current_scope = prev_scope
    
    def _block_always_returns(self, block: Block) -> bool:
        """Check if a block always returns a value (all paths end in return)."""
        for stmt in block.statements:
            if isinstance(stmt, ReturnStmt):
                return True
            elif isinstance(stmt, IfStmt):
                # If statement returns if: then returns AND (all elifs return) AND else returns
                then_returns = self._block_always_returns(stmt.then_block)
                
                # Must have else block to guarantee return
                if not stmt.else_block:
                    continue
                
                else_returns = self._block_always_returns(stmt.else_block)
                
                # Check all elif branches
                all_elifs_return = all(
                    self._block_always_returns(elif_branch.block) 
                    for elif_branch in stmt.elif_branches
                )
                
                if then_returns and else_returns and all_elifs_return:
                    return True
        
        return False
    
    def _check_const(self, decl: ConstDecl):
        """Type check a const declaration."""
        expected_type = self._resolve_type(decl.type)
        if not expected_type:
            return
        
        actual_type = self._check_expression(decl.value)
        if actual_type:
            self._check_type_match(expected_type, actual_type, decl.value.span,
                                   f"const '{decl.name}' has type mismatch")
    
    # ========================================================================
    # Statement Type Checking
    # ========================================================================
    
    def _check_statement(self, stmt: Statement):
        """Type check a statement."""
        if isinstance(stmt, Block):
            self._check_block(stmt)
        
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                actual_type = self._check_expression(stmt.value)
                if actual_type and self.current_function_return_type:
                    if isinstance(self.current_function_return_type, VoidType):
                        self._error("E_TYPE_MISMATCH",
                                   "cannot return a value from void function",
                                   stmt.span)
                    else:
                        self._check_type_match(self.current_function_return_type, actual_type,
                                              stmt.value.span, "return type mismatch")
            else:
                # Return with no value
                if self.current_function_return_type and not isinstance(self.current_function_return_type, VoidType):
                    self._error("E_TYPE_MISMATCH",
                               f"function must return a value of type {self._type_to_string(self.current_function_return_type)}",
                               stmt.span)
        
        elif isinstance(stmt, IfStmt):
            cond_type = self._check_expression(stmt.condition)
            if cond_type and not isinstance(cond_type, BoolType):
                self._error("E_TYPE_MISMATCH",
                           f"if condition must be bool, not {self._type_to_string(cond_type)}",
                           stmt.condition.span)
            self._check_block(stmt.then_block)
            for elif_branch in stmt.elif_branches:
                cond_type = self._check_expression(elif_branch.condition)
                if cond_type and not isinstance(cond_type, BoolType):
                    self._error("E_TYPE_MISMATCH",
                               f"elif condition must be bool, not {self._type_to_string(cond_type)}",
                               elif_branch.condition.span)
                self._check_block(elif_branch.block)
            if stmt.else_block:
                self._check_block(stmt.else_block)
        
        elif isinstance(stmt, ForStmt):
            # Check range expressions (should be integers)
            start_type = self._check_expression(stmt.range_start)
            end_type = self._check_expression(stmt.range_end)
            
            if start_type and not self._is_integer_type(start_type):
                self._error("E_TYPE_MISMATCH",
                           f"for loop range start must be integer, not {self._type_to_string(start_type)}",
                           stmt.range_start.span)
            
            if end_type and not self._is_integer_type(end_type):
                self._error("E_TYPE_MISMATCH",
                           f"for loop range end must be integer, not {self._type_to_string(end_type)}",
                           stmt.range_end.span)
            
            # Create loop scope with iterator variable
            loop_scope = Scope(parent=self.current_scope, level=self.current_scope.level + 1, kind='block')
            prev_scope = self.current_scope
            self.current_scope = loop_scope
            
            # Add iterator to scope (default to i32)
            iterator_symbol = Symbol(
                name=stmt.iterator_name,
                kind='let',
                decl_node=stmt,
                visibility=None,
                scope_level=loop_scope.level
            )
            loop_scope.define(stmt.iterator_name, iterator_symbol)
            
            self._check_block(stmt.body)
            
            self.current_scope = prev_scope
        
        elif isinstance(stmt, WhileStmt):
            # Check condition is boolean
            cond_type = self._check_expression(stmt.condition)
            if cond_type and not isinstance(cond_type, BoolType):
                self._error("E_TYPE_MISMATCH",
                           f"while condition must be bool, not {self._type_to_string(cond_type)}",
                           stmt.condition.span)
            self._check_block(stmt.body)
        
        elif isinstance(stmt, ExprStmt):
            self._check_expression(stmt.expression)
        
        elif isinstance(stmt, LetDecl):
            expected_type = self._resolve_type(stmt.type)
            
            # Add to current scope
            if expected_type:
                symbol = Symbol(
                    name=stmt.name,
                    kind='let',
                    decl_node=stmt,
                    visibility=None,
                    scope_level=self.current_scope.level
                )
                self.current_scope.define(stmt.name, symbol)
            
            if expected_type and stmt.initializer:
                actual_type = self._check_expression(stmt.initializer)
                if actual_type:
                    self._check_type_match(expected_type, actual_type, stmt.span,
                                          f"variable '{stmt.name}' initialization type mismatch")
        
        # Break and Continue don't need type checking (handled by semantic analysis)
    
    def _check_block(self, block: Block):
        """Type check a block of statements."""
        # Create new scope for block
        block_scope = Scope(parent=self.current_scope, level=self.current_scope.level + 1, kind='block')
        prev_scope = self.current_scope
        self.current_scope = block_scope
        
        for stmt in block.statements:
            self._check_statement(stmt)
        
        self.current_scope = prev_scope
    
    # ========================================================================
    # Expression Type Checking
    # ========================================================================
    
    def _check_expression(self, expr: Expression) -> Optional[BasisType]:
        """Type check an expression and return its type."""
        # Check if already computed
        expr_id = id(expr)
        if expr_id in self.expr_types:
            return self.expr_types[expr_id]
        
        result_type = None
        
        if isinstance(expr, LiteralExpr):
            result_type = self._check_literal(expr)
        
        elif isinstance(expr, IdentifierExpr):
            result_type = self._check_identifier(expr)
        
        elif isinstance(expr, BinaryExpr):
            result_type = self._check_binary(expr)
        
        elif isinstance(expr, UnaryExpr):
            result_type = self._check_unary(expr)
        
        elif isinstance(expr, CallExpr):
            result_type = self._check_call(expr)
        
        elif isinstance(expr, IndexExpr):
            result_type = self._check_index(expr)
        
        elif isinstance(expr, FieldAccessExpr):
            result_type = self._check_field_access(expr)
        
        elif isinstance(expr, AssignmentExpr):
            result_type = self._check_assignment(expr)
        
        elif isinstance(expr, AddressOfExpr):
            result_type = self._check_address_of(expr)
        
        elif isinstance(expr, DereferenceExpr):
            result_type = self._check_dereference(expr)
        
        elif isinstance(expr, CastExpr):
            result_type = self._check_cast(expr)
        
        elif isinstance(expr, ArrayLiteralExpr):
            result_type = self._check_array_literal(expr)
        
        elif isinstance(expr, ArrayRepeatExpr):
            result_type = self._check_array_repeat(expr)
        
        elif isinstance(expr, StructLiteralExpr):
            result_type = self._check_struct_literal(expr)
        
        # Cache the result
        if result_type:
            self.expr_types[expr_id] = result_type
        
        return result_type
    
    def _check_literal(self, expr: LiteralExpr) -> Optional[BasisType]:
        """Type check a literal expression."""
        if expr.kind == 'int':
            return BUILTIN_TYPES['i32']  # Default integer type
        elif expr.kind == 'float':
            return BUILTIN_TYPES['f64']  # Default float type
        elif expr.kind == 'bool':
            return BUILTIN_TYPES['bool']
        elif expr.kind == 'string':
            return PointerType(BUILTIN_TYPES['u8'])  # String literals are *u8
        return None
    
    def _check_identifier(self, expr: IdentifierExpr) -> Optional[BasisType]:
        """Type check an identifier expression."""
        # Look up the symbol
        symbol = self.current_scope.lookup(expr.name)
        if not symbol:
            # Should have been caught by semantic analysis
            return None
        
        # Get type from symbol's declaration
        if isinstance(symbol.decl_node, Param):
            return self._resolve_type(symbol.decl_node.type)
        elif isinstance(symbol.decl_node, LetDecl):
            return self._resolve_type(symbol.decl_node.type)
        elif isinstance(symbol.decl_node, ConstDecl):
            return self._resolve_type(symbol.decl_node.type)
        elif isinstance(symbol.decl_node, ForStmt):
            # Loop iterator variable - default to i32
            return BUILTIN_TYPES['i32']
        
        return None
    
    def _check_binary(self, expr: BinaryExpr) -> Optional[BasisType]:
        """Type check a binary expression."""
        left_type = self._check_expression(expr.left)
        right_type = self._check_expression(expr.right)
        
        if not left_type or not right_type:
            return None
        
        # Arithmetic operators: +, -, *, /, %
        if expr.operator in ['+', '-', '*', '/', '%']:
            # Pointer arithmetic: ptr + int or ptr - int
            if expr.operator in ['+', '-'] and isinstance(left_type, PointerType):
                if not self._is_integer_type(right_type):
                    self._error("E_TYPE_MISMATCH",
                               f"pointer arithmetic requires integer offset, got {self._type_to_string(right_type)}",
                               expr.right.span)
                    return None
                return left_type  # Result is same pointer type
            
            # Pointer arithmetic: int + ptr (commutative for +)
            if expr.operator == '+' and isinstance(right_type, PointerType):
                if not self._is_integer_type(left_type):
                    self._error("E_TYPE_MISMATCH",
                               f"pointer arithmetic requires integer offset, got {self._type_to_string(left_type)}",
                               expr.left.span)
                    return None
                return right_type  # Result is same pointer type
            
            if not self._is_numeric_type(left_type):
                self._error("E_TYPE_MISMATCH",
                           f"arithmetic operator '{expr.operator}' requires numeric operands, got {self._type_to_string(left_type)}",
                           expr.left.span)
                return None
            
            if not self._is_numeric_type(right_type):
                self._error("E_TYPE_MISMATCH",
                           f"arithmetic operator '{expr.operator}' requires numeric operands, got {self._type_to_string(right_type)}",
                           expr.right.span)
                return None
            
            if not self._types_equal(left_type, right_type):
                self._error("E_TYPE_MISMATCH",
                           f"arithmetic operands must have same type: {self._type_to_string(left_type)} vs {self._type_to_string(right_type)}",
                           expr.span)
                return None
            
            return left_type
        
        # Comparison operators: ==, !=, <, >, <=, >=
        elif expr.operator in ['==', '!=', '<', '>', '<=', '>=']:
            if not self._types_equal(left_type, right_type):
                self._error("E_TYPE_MISMATCH",
                           f"comparison operands must have same type: {self._type_to_string(left_type)} vs {self._type_to_string(right_type)}",
                           expr.span)
                return None
            
            return BUILTIN_TYPES['bool']
        
        # Logical operators: &&, ||
        elif expr.operator in ['&&', '||']:
            if not isinstance(left_type, BoolType):
                self._error("E_TYPE_MISMATCH",
                           f"logical operator '{expr.operator}' requires bool operands, got {self._type_to_string(left_type)}",
                           expr.left.span)
                return None
            
            if not isinstance(right_type, BoolType):
                self._error("E_TYPE_MISMATCH",
                           f"logical operator '{expr.operator}' requires bool operands, got {self._type_to_string(right_type)}",
                           expr.right.span)
                return None
            
            return BUILTIN_TYPES['bool']
        
        # Bitwise operators: &, |, ^, <<, >>
        elif expr.operator in ['&', '|', '^', '<<', '>>']:
            if not self._is_integer_type(left_type):
                self._error("E_TYPE_MISMATCH",
                           f"bitwise operator '{expr.operator}' requires integer operands, got {self._type_to_string(left_type)}",
                           expr.left.span)
                return None
            
            if not self._is_integer_type(right_type):
                self._error("E_TYPE_MISMATCH",
                           f"bitwise operator '{expr.operator}' requires integer operands, got {self._type_to_string(right_type)}",
                           expr.right.span)
                return None
            
            if not self._types_equal(left_type, right_type):
                self._error("E_TYPE_MISMATCH",
                           f"bitwise operands must have same type: {self._type_to_string(left_type)} vs {self._type_to_string(right_type)}",
                           expr.span)
                return None
            
            return left_type
        
        return None
    
    def _check_unary(self, expr: UnaryExpr) -> Optional[BasisType]:
        """Type check a unary expression."""
        operand_type = self._check_expression(expr.operand)
        
        if not operand_type:
            return None
        
        # Negation: -
        if expr.operator == '-':
            if not self._is_numeric_type(operand_type):
                self._error("E_TYPE_MISMATCH",
                           f"unary '-' requires numeric operand, got {self._type_to_string(operand_type)}",
                           expr.operand.span)
                return None
            return operand_type
        
        # Logical not: !
        elif expr.operator == '!':
            if not isinstance(operand_type, BoolType):
                self._error("E_TYPE_MISMATCH",
                           f"logical not requires bool operand, got {self._type_to_string(operand_type)}",
                           expr.operand.span)
                return None
            return BUILTIN_TYPES['bool']
        
        # Bitwise not: ~
        elif expr.operator == '~':
            if not self._is_integer_type(operand_type):
                self._error("E_TYPE_MISMATCH",
                           f"bitwise not requires integer operand, got {self._type_to_string(operand_type)}",
                           expr.operand.span)
                return None
            return operand_type
        
        return None
    
    def _check_call(self, expr: CallExpr) -> Optional[BasisType]:
        """Type check a function call."""
        # Get callee (should be a function)
        if isinstance(expr.callee, IdentifierExpr):
            symbol = self.current_scope.lookup(expr.callee.name)
            if symbol and isinstance(symbol.decl_node, FunctionDecl):
                func_decl = symbol.decl_node
                
                # Check argument count
                if len(expr.arguments) != len(func_decl.params):
                    self._error("E_TYPE_MISMATCH",
                               f"function '{func_decl.name}' expects {len(func_decl.params)} arguments, got {len(expr.arguments)}",
                               expr.span)
                    return None
                
                # Check argument types
                for i, (arg, param) in enumerate(zip(expr.arguments, func_decl.params)):
                    arg_type = self._check_expression(arg)
                    param_type = self._resolve_type(param.type)
                    
                    if arg_type and param_type:
                        if not self._types_equal(arg_type, param_type):
                            self._error("E_TYPE_MISMATCH",
                                       f"argument {i+1} type mismatch: expected {self._type_to_string(param_type)}, got {self._type_to_string(arg_type)}",
                                       arg.span)
                
                # Return function's return type
                return self._resolve_type(func_decl.return_type)
        
        return None
    
    def _check_index(self, expr: IndexExpr) -> Optional[BasisType]:
        """Type check an array/pointer indexing expression."""
        base_type = self._check_expression(expr.base)
        index_type = self._check_expression(expr.index)
        
        if not base_type or not index_type:
            return None
        
        # Index must be integer
        if not self._is_integer_type(index_type):
            self._error("E_TYPE_MISMATCH",
                       f"array index must be integer, got {self._type_to_string(index_type)}",
                       expr.index.span)
            return None
        
        # Base must be array or pointer
        if isinstance(base_type, ArrayType):
            # Store array size for runtime bounds checking in codegen
            if base_type.size is not None:
                expr.array_size = base_type.size
            
            # Check bounds for constant indices
            index_value = None
            
            # Try to evaluate the index to a constant
            if isinstance(expr.index, LiteralExpr) and expr.index.kind == 'int':
                try:
                    index_value = parse_int_literal(expr.index.value)
                except ValueError:
                    pass
            # Also handle unary negation of literals (e.g., -1, -5)
            elif isinstance(expr.index, UnaryExpr) and expr.index.operator == '-':
                if isinstance(expr.index.operand, LiteralExpr) and expr.index.operand.kind == 'int':
                    try:
                        index_value = -parse_int_literal(expr.index.operand.value)
                    except ValueError:
                        pass
            
            # Perform bounds checking if we could evaluate to a constant
            if index_value is not None and base_type.size is not None:
                if index_value < 0:
                    self._error("E_INDEX_OUT_OF_BOUNDS",
                               f"array index {index_value} is negative",
                               expr.index.span)
                elif index_value >= base_type.size:
                    self._error("E_INDEX_OUT_OF_BOUNDS",
                               f"array index {index_value} out of bounds for array of size {base_type.size}",
                               expr.index.span)
            
            return base_type.element
        elif isinstance(base_type, PointerType):
            return base_type.pointee
        else:
            self._error("E_TYPE_MISMATCH",
                       f"cannot index into non-array/pointer type {self._type_to_string(base_type)}",
                       expr.base.span)
            return None
    
    def _check_field_access(self, expr: FieldAccessExpr) -> Optional[BasisType]:
        """Type check a struct field access expression."""
        base_type = self._check_expression(expr.base)
        
        if not base_type:
            return None
        
        # Dereference pointer if needed (p.field auto-dereferences)
        if isinstance(base_type, PointerType):
            expr.base_is_pointer = True
            base_type = base_type.pointee
        
        # Base must be struct
        if not isinstance(base_type, StructType):
            self._error("E_TYPE_MISMATCH",
                       f"cannot access field of non-struct type {self._type_to_string(base_type)}",
                       expr.base.span)
            return None
        
        # Check if field exists
        if expr.field_name not in base_type.fields:
            self._error("E_TYPE_MISMATCH",
                       f"struct '{base_type.name}' has no field '{expr.field_name}'",
                       expr.span)
            return None
        
        return base_type.fields[expr.field_name]
    
    def _check_assignment(self, expr: AssignmentExpr) -> Optional[BasisType]:
        """Type check an assignment expression."""
        target_type = self._check_expression(expr.target)
        value_type = self._check_expression(expr.value)
        
        if not target_type or not value_type:
            return None
        
        # For compound assignments (+=, -=, etc.), check operator validity
        if expr.operator != '=':
            # Extract the operator (e.g., '+' from '+=')
            op = expr.operator[:-1]
            
            # Check if operator is valid for these types
            if op in ['+', '-', '*', '/', '%']:
                if not self._is_numeric_type(target_type):
                    self._error("E_TYPE_MISMATCH",
                               f"compound assignment '{expr.operator}' requires numeric target, got {self._type_to_string(target_type)}",
                               expr.target.span)
                    return None
            elif op in ['&', '|', '^', '<<', '>>']:
                if not self._is_integer_type(target_type):
                    self._error("E_TYPE_MISMATCH",
                               f"compound assignment '{expr.operator}' requires integer target, got {self._type_to_string(target_type)}",
                               expr.target.span)
                    return None
        
        # Check type match
        if not self._types_equal(target_type, value_type):
            self._error("E_TYPE_MISMATCH",
                       f"assignment type mismatch: cannot assign {self._type_to_string(value_type)} to {self._type_to_string(target_type)}",
                       expr.span)
            return None
        
        return target_type
    
    def _check_address_of(self, expr: AddressOfExpr) -> Optional[BasisType]:
        """Type check an address-of expression."""
        operand_type = self._check_expression(expr.operand)
        
        if not operand_type:
            return None
        
        # Cannot take address of void
        if isinstance(operand_type, VoidType):
            self._error("E_TYPE_MISMATCH",
                       "cannot take address of void",
                       expr.operand.span)
            return None
        
        return PointerType(operand_type)
    
    def _check_dereference(self, expr: DereferenceExpr) -> Optional[BasisType]:
        """Type check a dereference expression."""
        operand_type = self._check_expression(expr.operand)
        
        if not operand_type:
            return None
        
        # Operand must be pointer
        if not isinstance(operand_type, PointerType):
            self._error("E_TYPE_MISMATCH",
                       f"cannot dereference non-pointer type {self._type_to_string(operand_type)}",
                       expr.operand.span)
            return None
        
        return operand_type.pointee
    
    def _check_array_literal(self, expr: ArrayLiteralExpr) -> Optional[BasisType]:
        """Type check an array literal expression."""
        if not expr.elements:
            # Empty array - we can't infer type without context
            self._error("E_TYPE_INFERENCE",
                       "cannot infer type of empty array literal, please use type annotation",
                       expr.span)
            return None
        
        # Type check all elements
        element_types = []
        for elem in expr.elements:
            elem_type = self._check_expression(elem)
            if elem_type:
                element_types.append(elem_type)
        
        if not element_types:
            return None
        
        # All elements must have the same type
        first_type = element_types[0]
        for i, elem_type in enumerate(element_types[1:], 1):
            if not self._types_equal(first_type, elem_type):
                self._error("E_TYPE_MISMATCH",
                           f"array literal element {i} has type {self._type_to_string(elem_type)}, "
                           f"but element 0 has type {self._type_to_string(first_type)}",
                           expr.elements[i].span)
                return None
        
        # Return array type (size is length of elements)
        return ArrayType(first_type, len(expr.elements))
    
    def _check_array_repeat(self, expr: ArrayRepeatExpr) -> Optional[BasisType]:
        """Type check an array repeat expression: [value; count] or [value; count | idx: val, ...]."""
        # Type check the default value
        value_type = self._check_expression(expr.value)
        if not value_type:
            return None
        
        # Type check the count expression (must be compile-time constant integer)
        count_type = self._check_expression(expr.count)
        if not count_type:
            return None
        
        if not self._is_integer_type(count_type):
            self._error("E_TYPE_MISMATCH",
                       f"array repeat count must be an integer, got {self._type_to_string(count_type)}",
                       expr.count.span)
            return None
        
        # Try to evaluate count at compile time
        count = None
        if isinstance(expr.count, LiteralExpr) and expr.count.kind == 'int':
            try:
                count = parse_int_literal(expr.count.value)
            except ValueError:
                pass
        
        if count is None:
            self._error("E_NOT_CONSTANT",
                       "array repeat count must be a compile-time constant",
                       expr.count.span)
            return None
        
        if count < 0:
            self._error("E_INVALID_SIZE",
                       f"array repeat count cannot be negative: {count}",
                       expr.count.span)
            return None
        
        # Type check override expressions
        for override in expr.overrides:
            # Check index type
            idx_type = self._check_expression(override.index)
            if idx_type and not self._is_integer_type(idx_type):
                self._error("E_TYPE_MISMATCH",
                           f"array override index must be an integer, got {self._type_to_string(idx_type)}",
                           override.index.span)
            
            # Try to evaluate index and check bounds
            if isinstance(override.index, LiteralExpr) and override.index.kind == 'int':
                try:
                    idx = parse_int_literal(override.index.value)
                    if idx < 0 or idx >= count:
                        self._error("E_INDEX_OUT_OF_BOUNDS",
                                   f"array override index {idx} out of bounds for array of size {count}",
                                   override.index.span)
                except ValueError:
                    pass
            
            # Check value type matches default type
            val_type = self._check_expression(override.value)
            if val_type and not self._types_equal(value_type, val_type):
                self._error("E_TYPE_MISMATCH",
                           f"array override value has type {self._type_to_string(val_type)}, "
                           f"but array element type is {self._type_to_string(value_type)}",
                           override.value.span)
        
        return ArrayType(value_type, count)
    
    def _check_struct_literal(self, expr: StructLiteralExpr) -> Optional[BasisType]:
        """Type check a struct literal expression."""
        # Look up struct type
        if expr.struct_name not in self.struct_types:
            self._error("E_TYPE_UNKNOWN",
                       f"unknown struct type '{expr.struct_name}'",
                       expr.span)
            return None
        
        struct_type = self.struct_types[expr.struct_name]
        
        # Check that all required fields are initialized
        initialized_fields = set()
        for field_init in expr.field_inits:
            field_name = field_init.field_name
            
            # Check if field exists in struct
            if field_name not in struct_type.fields:
                self._error("E_TYPE_FIELD",
                           f"struct '{expr.struct_name}' has no field '{field_name}'",
                           field_init.span)
                continue
            
            # Check for duplicate field initialization
            if field_name in initialized_fields:
                self._error("E_TYPE_FIELD",
                           f"field '{field_name}' initialized multiple times",
                           field_init.span)
                continue
            
            initialized_fields.add(field_name)
            
            # Type check the field value
            expected_type = struct_type.fields[field_name]
            actual_type = self._check_expression(field_init.value)
            
            if actual_type and not self._types_equal(expected_type, actual_type):
                self._error("E_TYPE_MISMATCH",
                           f"field '{field_name}' has type {self._type_to_string(expected_type)}, "
                           f"but initializer has type {self._type_to_string(actual_type)}",
                           field_init.value.span)
        
        # Check that all fields were initialized
        for field_name in struct_type.fields:
            if field_name not in initialized_fields:
                self._error("E_TYPE_FIELD",
                           f"missing initialization for field '{field_name}'",
                           expr.span)
        
        return struct_type
    
    def _check_cast(self, expr: CastExpr) -> Optional[BasisType]:
        """Type check a cast expression with validation."""
        source_type = self._check_expression(expr.expression)
        target_type = self._resolve_type(expr.target_type)
        
        if source_type is None or target_type is None:
            return target_type
        
        # Allow numeric <-> numeric (int/float in any direction)
        src_numeric = isinstance(source_type, (IntType, FloatType))
        tgt_numeric = isinstance(target_type, (IntType, FloatType))
        if src_numeric and tgt_numeric:
            return target_type
        
        # Allow pointer <-> pointer
        src_ptr = isinstance(source_type, PointerType)
        tgt_ptr = isinstance(target_type, PointerType)
        if src_ptr and tgt_ptr:
            return target_type
        
        # Allow integer <-> pointer (for MMIO addresses)
        if isinstance(source_type, IntType) and tgt_ptr:
            return target_type
        if src_ptr and isinstance(target_type, IntType):
            return target_type
        
        # Allow bool -> integer
        if isinstance(source_type, BoolType) and isinstance(target_type, IntType):
            return target_type
        
        # Reject everything else
        self._error(
            "E_INVALID_CAST",
            f"cannot cast '{self._type_to_string(source_type)}' to '{self._type_to_string(target_type)}'",
            expr.span
        )
        return target_type
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    def _is_numeric_type(self, t: BasisType) -> bool:
        """Check if type is numeric (integer or float)."""
        return isinstance(t, (IntType, FloatType))
    
    def _is_integer_type(self, t: BasisType) -> bool:
        """Check if type is integer."""
        return isinstance(t, IntType)
    
    def _types_equal(self, t1: BasisType, t2: BasisType) -> bool:
        """Check if two types are equal (no implicit conversions)."""
        return t1 == t2
    
    def _check_type_match(self, expected: BasisType, actual: BasisType, span: SourceSpan, message: str):
        """Check if actual type matches expected type."""
        # Check basic type equality
        types_equal = self._types_equal(expected, actual)
        
        if not types_equal:
            self._error("E_TYPE_MISMATCH",
                       f"{message}: expected {self._type_to_string(expected)}, got {self._type_to_string(actual)}",
                       span)
        
        # Additional validation for array types (check even if types are equal in structure)
        if isinstance(expected, ArrayType) and isinstance(actual, ArrayType):
            # Check if sizes match when both are known
            if expected.size is not None and actual.size is not None:
                if expected.size != actual.size:
                    self._error("E_TYPE_MISMATCH",
                               f"{message}: expected array of size {expected.size}, got array of size {actual.size}",
                               span)
    
    def _type_to_string(self, t: BasisType) -> str:
        """Convert type to string for error messages."""
        if isinstance(t, IntType):
            return t.name
        elif isinstance(t, FloatType):
            return t.name
        elif isinstance(t, BoolType):
            return 'bool'
        elif isinstance(t, VoidType):
            return 'void'
        elif isinstance(t, PointerType):
            return f'*{self._type_to_string(t.pointee)}'
        elif isinstance(t, ArrayType):
            return f'[{self._type_to_string(t.element)}; N]'
        elif isinstance(t, StructType):
            return t.name
        elif isinstance(t, VolatilePointerType):
            return f'volatile {self._type_to_string(t.pointee)}'
        return '<unknown>'
    
    def _error(self, code: str, message: str, span: SourceSpan):
        """Report a type error."""
        self.diag.error(code, message, span.start_line, span.start_col,
                       filename=f"<{self.current_module_name}>")


# ============================================================================
# Convenience Function
# ============================================================================

def check_types(module: Module, diag: DiagnosticEngine, module_scope: Scope) -> bool:
    """
    Convenience function to type check a module.
    Returns True if type checking succeeds (no errors).
    """
    checker = TypeChecker(diag, module_scope)
    return checker.check(module)
