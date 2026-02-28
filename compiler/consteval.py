"""
BASIS Compile-Time Constant Evaluator
Evaluates constant expressions at compile time.
Does NOT optimize or fold runtime expressions.
"""

from typing import Optional, Union
from dataclasses import dataclass
from ast_defs import *
from diagnostics import DiagnosticEngine
from typecheck import TypeChecker, BasisType, IntType, FloatType, BoolType


# ============================================================================
# Constant Value Representation
# ============================================================================

@dataclass
class ConstantValue:
    """Represents a compile-time constant value."""
    pass


@dataclass
class IntConstant(ConstantValue):
    """Integer constant value."""
    value: int
    type_name: str  # "i32", "u64", etc.
    
    def __repr__(self):
        return f"{self.value}:{self.type_name}"


@dataclass
class FloatConstant(ConstantValue):
    """Floating-point constant value."""
    value: float
    type_name: str  # "f32", "f64"
    
    def __repr__(self):
        return f"{self.value}:{self.type_name}"


@dataclass
class BoolConstant(ConstantValue):
    """Boolean constant value."""
    value: bool
    
    def __repr__(self):
        return f"{self.value}:bool"


# ============================================================================
# Constant Evaluator
# ============================================================================

class ConstantEvaluator:
    """
    Evaluates compile-time constant expressions.
    Does NOT fold runtime expressions or perform optimizations.
    """
    
    def __init__(self, diag_engine: DiagnosticEngine, type_checker: TypeChecker):
        self.diag = diag_engine
        self.type_checker = type_checker
        
        # Cache of evaluated constants
        self.const_values: dict = {}  # symbol name -> ConstantValue
        
        # Current module name for error messages
        self.current_module_name: str = ""
    
    # ========================================================================
    # Public API
    # ========================================================================
    
    def is_constant(self, expr: Expression) -> bool:
        """
        Check if an expression is a compile-time constant.
        Returns True if the expression can be evaluated at compile time.
        """
        try:
            self.eval_constant(expr)
            return True
        except (ValueError, TypeError):
            return False
    
    def eval_constant(self, expr: Expression) -> ConstantValue:
        """
        Evaluate a compile-time constant expression.
        Raises exception if expression is not constant.
        Returns the evaluated constant value.
        """
        if isinstance(expr, LiteralExpr):
            return self._eval_literal(expr)
        
        elif isinstance(expr, IdentifierExpr):
            return self._eval_identifier(expr)
        
        elif isinstance(expr, UnaryExpr):
            return self._eval_unary(expr)
        
        elif isinstance(expr, BinaryExpr):
            return self._eval_binary(expr)
        
        elif isinstance(expr, CastExpr):
            # Cast of a constant preserves value but applies target type
            inner = self.eval_constant(expr.expression)
            # Extract target type name
            target = expr.target_type
            if isinstance(target, TypeName):
                type_name = target.name
            elif isinstance(target, PointerType):
                # Pointer casts aren't meaningful for const values
                return inner
            else:
                return inner
            # Apply type to integer constants
            if isinstance(inner, IntConstant):
                return IntConstant(inner.value, type_name)
            elif isinstance(inner, FloatConstant):
                if type_name in ('i8','i16','i32','i64','u8','u16','u32','u64'):
                    return IntConstant(int(inner.value), type_name)
                return FloatConstant(inner.value, type_name)
            return inner
        
        else:
            # All other expressions are not constant
            self._error("E_NOT_CONSTANT",
                       f"expression is not a compile-time constant",
                       expr.span)
            raise ValueError("Not a constant expression")
    
    def evaluate_module_constants(self, module: Module):
        """
        First pass: evaluate all const declarations in the module.
        This populates the const_values cache.
        """
        self.current_module_name = module.name
        
        for decl in module.declarations:
            if isinstance(decl, ConstDecl):
                try:
                    value = self.eval_constant(decl.value)
                    self.const_values[decl.name] = value
                except:
                    # Error already reported
                    pass
    
    def validate_array_sizes(self, module: Module):
        """
        Second pass: validate that all array size expressions are constant integers.
        """
        for decl in module.declarations:
            self._validate_decl_array_sizes(decl)
    
    # ========================================================================
    # Literal Evaluation
    # ========================================================================
    
    def _eval_literal(self, expr: LiteralExpr) -> ConstantValue:
        """Evaluate a literal expression."""
        if expr.kind == 'int':
            # Default to i32 for integer literals
            return IntConstant(parse_int_literal(expr.value), 'i32')
        
        elif expr.kind == 'float':
            # Default to f64 for float literals
            return FloatConstant(float(expr.value), 'f64')
        
        elif expr.kind == 'bool':
            return BoolConstant(expr.value.lower() == 'true')
        
        else:
            # String literals are not compile-time constants
            self._error("E_NOT_CONSTANT",
                       "string literals are not compile-time constants",
                       expr.span)
            raise ValueError("String literal")
    
    # ========================================================================
    # Identifier Evaluation
    # ========================================================================
    
    def _eval_identifier(self, expr: IdentifierExpr) -> ConstantValue:
        """Evaluate an identifier (must be a const)."""
        # Check if it's a previously evaluated const
        if expr.name in self.const_values:
            return self.const_values[expr.name]
        
        # Not a const or not yet evaluated
        self._error("E_NOT_CONSTANT",
                   f"'{expr.name}' is not a compile-time constant",
                   expr.span)
        raise ValueError("Not a constant identifier")
    
    # ========================================================================
    # Unary Expression Evaluation
    # ========================================================================
    
    def _eval_unary(self, expr: UnaryExpr) -> ConstantValue:
        """Evaluate a unary expression on a constant."""
        operand = self.eval_constant(expr.operand)
        
        # Unary plus (+)
        if expr.operator == '+':
            if isinstance(operand, IntConstant):
                return operand
            elif isinstance(operand, FloatConstant):
                return operand
            else:
                self._error("E_INVALID_CONST_OP",
                           "unary '+' requires numeric operand",
                           expr.span)
                raise ValueError("Invalid unary +")
        
        # Unary minus (-)
        elif expr.operator == '-':
            if isinstance(operand, IntConstant):
                return IntConstant(-operand.value, operand.type_name)
            elif isinstance(operand, FloatConstant):
                return FloatConstant(-operand.value, operand.type_name)
            else:
                self._error("E_INVALID_CONST_OP",
                           "unary '-' requires numeric operand",
                           expr.span)
                raise ValueError("Invalid unary -")
        
        # Logical not (!)
        elif expr.operator == '!':
            if isinstance(operand, BoolConstant):
                return BoolConstant(not operand.value)
            else:
                self._error("E_INVALID_CONST_OP",
                           "logical '!' requires bool operand",
                           expr.span)
                raise ValueError("Invalid unary !")
        
        # Bitwise not (~)
        elif expr.operator == '~':
            if isinstance(operand, IntConstant):
                # Bitwise not - result depends on type width
                return IntConstant(~operand.value, operand.type_name)
            else:
                self._error("E_INVALID_CONST_OP",
                           "bitwise '~' requires integer operand",
                           expr.span)
                raise ValueError("Invalid unary ~")
        
        else:
            self._error("E_INVALID_CONST_OP",
                       f"unknown unary operator '{expr.operator}'",
                       expr.span)
            raise ValueError("Unknown operator")
    
    # ========================================================================
    # Binary Expression Evaluation
    # ========================================================================
    
    def _eval_binary(self, expr: BinaryExpr) -> ConstantValue:
        """Evaluate a binary expression on constants."""
        left = self.eval_constant(expr.left)
        right = self.eval_constant(expr.right)
        
        # Type compatibility check
        if type(left) != type(right):
            self._error("E_INVALID_CONST_OP",
                       f"operands must have compatible types in constant expression",
                       expr.span)
            raise ValueError("Type mismatch")
        
        # Arithmetic operators
        if expr.operator in ['+', '-', '*', '/', '%']:
            return self._eval_arithmetic(expr.operator, left, right, expr.span)
        
        # Comparison operators
        elif expr.operator in ['==', '!=', '<', '>', '<=', '>=']:
            return self._eval_comparison(expr.operator, left, right, expr.span)
        
        # Logical operators
        elif expr.operator in ['&&', '||']:
            return self._eval_logical(expr.operator, left, right, expr.span)
        
        # Bitwise operators
        elif expr.operator in ['&', '|', '^', '<<', '>>']:
            return self._eval_bitwise(expr.operator, left, right, expr.span)
        
        else:
            self._error("E_INVALID_CONST_OP",
                       f"operator '{expr.operator}' not supported in constant expressions",
                       expr.span)
            raise ValueError("Unsupported operator")
    
    def _eval_arithmetic(self, op: str, left: ConstantValue, right: ConstantValue, 
                        span: SourceSpan) -> ConstantValue:
        """Evaluate arithmetic operations."""
        if isinstance(left, IntConstant) and isinstance(right, IntConstant):
            # Integer arithmetic
            if op == '+':
                result = left.value + right.value
            elif op == '-':
                result = left.value - right.value
            elif op == '*':
                result = left.value * right.value
            elif op == '/':
                if right.value == 0:
                    self._error("E_DIV_BY_ZERO",
                               "division by zero in constant expression",
                               span)
                    raise ValueError("Division by zero")
                result = left.value // right.value  # Integer division
            elif op == '%':
                if right.value == 0:
                    self._error("E_DIV_BY_ZERO",
                               "modulo by zero in constant expression",
                               span)
                    raise ValueError("Modulo by zero")
                result = left.value % right.value
            else:
                raise ValueError(f"Unknown operator {op}")
            
            return IntConstant(result, left.type_name)
        
        elif isinstance(left, FloatConstant) and isinstance(right, FloatConstant):
            # Float arithmetic
            if op == '+':
                result = left.value + right.value
            elif op == '-':
                result = left.value - right.value
            elif op == '*':
                result = left.value * right.value
            elif op == '/':
                if right.value == 0.0:
                    self._error("E_DIV_BY_ZERO",
                               "division by zero in constant expression",
                               span)
                    raise ValueError("Division by zero")
                result = left.value / right.value
            elif op == '%':
                self._error("E_INVALID_CONST_OP",
                           "modulo operator '%' not supported for floating-point",
                           span)
                raise ValueError("Float modulo")
            else:
                raise ValueError(f"Unknown operator {op}")
            
            return FloatConstant(result, left.type_name)
        
        else:
            self._error("E_INVALID_CONST_OP",
                       f"arithmetic operator '{op}' requires numeric operands",
                       span)
            raise ValueError("Invalid arithmetic")
    
    def _eval_comparison(self, op: str, left: ConstantValue, right: ConstantValue,
                        span: SourceSpan) -> BoolConstant:
        """Evaluate comparison operations."""
        if isinstance(left, IntConstant) and isinstance(right, IntConstant):
            if op == '==':
                result = left.value == right.value
            elif op == '!=':
                result = left.value != right.value
            elif op == '<':
                result = left.value < right.value
            elif op == '>':
                result = left.value > right.value
            elif op == '<=':
                result = left.value <= right.value
            elif op == '>=':
                result = left.value >= right.value
            else:
                raise ValueError(f"Unknown operator {op}")
            
            return BoolConstant(result)
        
        elif isinstance(left, FloatConstant) and isinstance(right, FloatConstant):
            if op == '==':
                result = left.value == right.value
            elif op == '!=':
                result = left.value != right.value
            elif op == '<':
                result = left.value < right.value
            elif op == '>':
                result = left.value > right.value
            elif op == '<=':
                result = left.value <= right.value
            elif op == '>=':
                result = left.value >= right.value
            else:
                raise ValueError(f"Unknown operator {op}")
            
            return BoolConstant(result)
        
        elif isinstance(left, BoolConstant) and isinstance(right, BoolConstant):
            if op == '==':
                result = left.value == right.value
            elif op == '!=':
                result = left.value != right.value
            else:
                self._error("E_INVALID_CONST_OP",
                           f"operator '{op}' not supported for bool",
                           span)
                raise ValueError("Invalid bool comparison")
            
            return BoolConstant(result)
        
        else:
            self._error("E_INVALID_CONST_OP",
                       "comparison requires compatible types",
                       span)
            raise ValueError("Invalid comparison")
    
    def _eval_logical(self, op: str, left: ConstantValue, right: ConstantValue,
                     span: SourceSpan) -> BoolConstant:
        """Evaluate logical operations."""
        if not isinstance(left, BoolConstant) or not isinstance(right, BoolConstant):
            self._error("E_INVALID_CONST_OP",
                       f"logical operator '{op}' requires bool operands",
                       span)
            raise ValueError("Invalid logical operation")
        
        if op == '&&':
            return BoolConstant(left.value and right.value)
        elif op == '||':
            return BoolConstant(left.value or right.value)
        else:
            raise ValueError(f"Unknown operator {op}")
    
    def _eval_bitwise(self, op: str, left: ConstantValue, right: ConstantValue,
                     span: SourceSpan) -> IntConstant:
        """Evaluate bitwise operations."""
        if not isinstance(left, IntConstant) or not isinstance(right, IntConstant):
            self._error("E_INVALID_CONST_OP",
                       f"bitwise operator '{op}' requires integer operands",
                       span)
            raise ValueError("Invalid bitwise operation")
        
        if op == '&':
            result = left.value & right.value
        elif op == '|':
            result = left.value | right.value
        elif op == '^':
            result = left.value ^ right.value
        elif op == '<<':
            result = left.value << right.value
        elif op == '>>':
            result = left.value >> right.value
        else:
            raise ValueError(f"Unknown operator {op}")
        
        return IntConstant(result, left.type_name)
    
    # ========================================================================
    # Array Size Validation
    # ========================================================================
    
    def _validate_decl_array_sizes(self, decl: Declaration):
        """Validate array sizes in a declaration."""
        if isinstance(decl, FunctionDecl):
            # Check parameters
            for param in decl.params:
                self._validate_type_array_sizes(param.type)
            
            # Check return type
            self._validate_type_array_sizes(decl.return_type)
            
            # Check function body
            if decl.body:
                self._validate_block_array_sizes(decl.body)
        
        elif isinstance(decl, StructDecl):
            for field in decl.fields:
                self._validate_type_array_sizes(field.type)
        
        elif isinstance(decl, LetDecl):
            self._validate_type_array_sizes(decl.type)
        
        elif isinstance(decl, ConstDecl):
            self._validate_type_array_sizes(decl.type)
    
    def _validate_type_array_sizes(self, type_node: Type):
        """Validate array sizes in a type."""
        if isinstance(type_node, ArrayType):
            # Validate element type first
            self._validate_type_array_sizes(type_node.element_type)
            
            # Validate size expression is constant and integer
            try:
                size_value = self.eval_constant(type_node.size_expr)
                
                if not isinstance(size_value, IntConstant):
                    self._error("E_INVALID_ARRAY_SIZE",
                               "array size must be an integer constant",
                               type_node.size_expr.span)
                elif size_value.value <= 0:
                    self._error("E_INVALID_ARRAY_SIZE",
                               f"array size must be positive, got {size_value.value}",
                               type_node.size_expr.span)
            except:
                # Error already reported by eval_constant
                pass
        
        elif isinstance(type_node, PointerType):
            self._validate_type_array_sizes(type_node.base_type)
    
    def _validate_block_array_sizes(self, block: Block):
        """Validate array sizes in a block."""
        for stmt in block.statements:
            self._validate_stmt_array_sizes(stmt)
    
    def _validate_stmt_array_sizes(self, stmt: Statement):
        """Validate array sizes in a statement."""
        if isinstance(stmt, Block):
            self._validate_block_array_sizes(stmt)
        
        elif isinstance(stmt, LetDecl):
            self._validate_type_array_sizes(stmt.type)
        
        elif isinstance(stmt, IfStmt):
            self._validate_block_array_sizes(stmt.then_block)
            for elif_branch in stmt.elif_branches:
                self._validate_block_array_sizes(elif_branch.block)
            if stmt.else_block:
                self._validate_block_array_sizes(stmt.else_block)
        
        elif isinstance(stmt, ForStmt):
            self._validate_block_array_sizes(stmt.body)
    
    # ========================================================================
    # Error Reporting
    # ========================================================================
    
    def _error(self, code: str, message: str, span: SourceSpan):
        """Report a constant evaluation error."""
        self.diag.error(code, message, span.start_line, span.start_col,
                       filename=f"<{self.current_module_name}>")


# ============================================================================
# Convenience Functions
# ============================================================================

def evaluate_constants(module: Module, diag: DiagnosticEngine, 
                      type_checker: TypeChecker) -> ConstantEvaluator:
    """
    Convenience function to evaluate all constants in a module.
    Returns the evaluator for further queries.
    """
    evaluator = ConstantEvaluator(diag, type_checker)
    evaluator.evaluate_module_constants(module)
    evaluator.validate_array_sizes(module)
    return evaluator
