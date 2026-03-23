"""
BASIS Loop Bound Analysis
Determines whether for-loops are provably bounded.
Attaches max_iteration_count metadata to loops.
"""

from typing import Optional, Dict, Set
from dataclasses import dataclass
from ast_defs import *
from diagnostics import DiagnosticEngine
from consteval import ConstantEvaluator, IntConstant
from sema import Scope


# ============================================================================
# Loop Bound Representation
# ============================================================================

@dataclass
class LoopBound:
    """Represents a loop bound with iteration count."""
    max_iterations: int
    is_constant: bool  # True if computed from constants only
    
    def __repr__(self):
        return f"LoopBound(max_iterations={self.max_iterations})"


# ============================================================================
# Loop Analyzer
# ============================================================================

class LoopAnalyzer:
    """
    Analyzes loops to determine if they are provably bounded.
    Attaches max_iteration_count metadata to loop nodes.
    """
    
    def __init__(self, diag_engine: DiagnosticEngine, 
                 const_eval: ConstantEvaluator,
                 module_scope: Scope):
        self.diag = diag_engine
        self.const_eval = const_eval
        self.module_scope = module_scope
        
        # Loop metadata: maps loop node id to LoopBound
        self.loop_bounds: Dict[int, LoopBound] = {}
        
        # Bounded parameters: function parameters with known max values
        # These would come from annotations like @bounded(max=100)
        # For now, we track them as we discover them
        self.bounded_params: Dict[str, int] = {}
        
        # Current module name
        self.current_module_name: str = ""
        
        # Current function scope (for parameter lookups)
        self.current_function_scope: Optional[Scope] = None
        
        # Nesting level tracking for nested loop analysis
        self.loop_nesting_level: int = 0
    
    # ========================================================================
    # Main Entry Point
    # ========================================================================
    
    def analyze(self, module: Module) -> bool:
        """
        Analyze all loops in the module.
        Returns True if successful (no errors).
        """
        self.current_module_name = module.name
        
        for decl in module.declarations:
            self._analyze_declaration(decl)
        
        return not self.diag.has_errors()
    
    # ========================================================================
    # Declaration Analysis
    # ========================================================================
    
    def _analyze_declaration(self, decl: Declaration):
        """Analyze a declaration for loops."""
        if isinstance(decl, FunctionDecl):
            self._analyze_function(decl)
    
    def _analyze_function(self, decl: FunctionDecl):
        """Analyze a function for loops."""
        if not decl.body:
            return
        
        # Create function scope for parameter tracking
        func_scope = Scope(parent=self.module_scope, level=1, kind='function')
        self.current_function_scope = func_scope
        
        # Extract bounded parameter information from annotations
        # In a full implementation, this would parse @bounded(max=N) annotations
        # For this demo, we'll recognize parameters named with _bounded suffix
        for param in decl.params:
            if param.name.endswith('_bounded'):
                # Demo: assume bounded parameters have max value of 1000
                self.bounded_params[param.name] = 1000
        
        self._analyze_block(decl.body)
        
        self.current_function_scope = None
        self.bounded_params.clear()
    
    # ========================================================================
    # Statement Analysis
    # ========================================================================
    
    def _analyze_block(self, block: Block):
        """Analyze a block for loops."""
        for stmt in block.statements:
            self._analyze_statement(stmt)
    
    def _analyze_statement(self, stmt: Statement):
        """Analyze a statement for loops."""
        if isinstance(stmt, Block):
            self._analyze_block(stmt)
        
        elif isinstance(stmt, ForStmt):
            self._analyze_loop(stmt)
        
        elif isinstance(stmt, WhileStmt):
            self._analyze_while_loop(stmt)
        
        elif isinstance(stmt, IfStmt):
            self._analyze_block(stmt.then_block)
            for elif_branch in stmt.elif_branches:
                self._analyze_block(elif_branch.block)
            if stmt.else_block:
                self._analyze_block(stmt.else_block)
    
    # ========================================================================
    # Loop Analysis
    # ========================================================================
    
    def _analyze_loop(self, loop: ForStmt):
        """Analyze a for loop to determine its bounds."""
        # Track nesting level
        prev_nesting = self.loop_nesting_level
        self.loop_nesting_level += 1
        
        # Try to evaluate start and end as constants or bounded values
        start_result = self._evaluate_bound_expr(loop.range_start)
        end_result = self._evaluate_bound_expr(loop.range_end)
        
        if start_result is None:
            # Start bound could not be determined
            # Don't analyze nested loops if outer loop is unbounded
            self.loop_nesting_level = prev_nesting
            return
        
        if end_result is None:
            # End bound could not be determined
            # Don't analyze nested loops if outer loop is unbounded
            self.loop_nesting_level = prev_nesting
            return
        
        # Unpack results: (value, is_constant)
        start_value, start_is_const = start_result
        end_value, end_is_const = end_result
        
        # Both bounds must be provable; propagate is_constant based on both
        is_constant = start_is_const and end_is_const
        
        # Calculate iteration count
        if end_value <= start_value:
            iteration_count = 0
        else:
            iteration_count = end_value - start_value
        
        # Check for unreasonably large bounds
        if iteration_count > 1_000_000_000:
            self._warning("W_LARGE_LOOP_BOUND",
                         f"loop has very large bound: {iteration_count} iterations",
                         loop.span)
        
        # Store the bound with correct is_constant flag
        bound = LoopBound(max_iterations=iteration_count, is_constant=is_constant)
        self.loop_bounds[id(loop)] = bound
        
        # Analyze nested loops in the body
        self._analyze_block(loop.body)
        
        self.loop_nesting_level = prev_nesting
    
    def _analyze_while_loop(self, stmt: WhileStmt):
        self._error(
            "E_WHILE_REMOVED",
            "while loops are not part of BASIS; use a bounded for loop or recursion with @recursion(max=N)",
            stmt.span,
        )
    
    def _evaluate_bound_expr(self, expr: Expression) -> Optional[tuple]:
        """
        Try to evaluate an expression as a loop bound.
        Returns tuple of (value: int, is_constant: bool) if successful, None otherwise.
        - is_constant=True: bound from constant expression
        - is_constant=False: bound from bounded parameter
        """
        # Check if it's an identifier first (could be bounded parameter)
        if isinstance(expr, IdentifierExpr):
            # Check if it's a bounded parameter (symbolic bound)
            if expr.name in self.bounded_params:
                # Bounded parameter: return value with is_constant=False
                return (self.bounded_params[expr.name], False)
        
        # Try constant evaluation
        if self.const_eval.is_constant(expr):
            try:
                value = self.const_eval.eval_constant(expr)
                if isinstance(value, IntConstant):
                    # Constant expression: return value with is_constant=True
                    return (value.value, True)
                else:
                    # Not an integer constant
                    self._error("E_UNBOUNDED_LOOP",
                               "loop bound must be an integer constant",
                               expr.span)
                    return None
            except:
                # Evaluation failed, continue to other checks
                pass
        
        # Check for specific disallowed expression types
        if isinstance(expr, IdentifierExpr):
            # Not a constant and not a bounded parameter
            self._error("E_UNBOUNDED_LOOP",
                       f"loop bound '{expr.name}' is not a compile-time constant or bounded parameter",
                       expr.span)
            return None
        
        # Check for function calls
        if isinstance(expr, CallExpr):
            self._error("E_UNBOUNDED_LOOP",
                       "function calls are not allowed in loop bounds",
                       expr.span)
            return None
        
        # Check for pointer dereference
        if isinstance(expr, DereferenceExpr):
            self._error("E_UNBOUNDED_LOOP",
                       "pointer dereference not allowed in loop bounds",
                       expr.span)
            return None
        
        # Check for field access
        if isinstance(expr, FieldAccessExpr):
            self._error("E_UNBOUNDED_LOOP",
                       "field access not allowed in loop bounds",
                       expr.span)
            return None
        
        # Check for array indexing
        if isinstance(expr, IndexExpr):
            self._error("E_UNBOUNDED_LOOP",
                       "array indexing not allowed in loop bounds",
                       expr.span)
            return None
        
        # Generic error for other expression types
        self._error("E_UNBOUNDED_LOOP",
                   "loop bound must be a compile-time constant",
                   expr.span)
        return None
    
    # ========================================================================
    # Query Interface
    # ========================================================================
    
    def get_loop_bound(self, loop: ForStmt) -> Optional[LoopBound]:
        """Get the bound for a loop."""
        return self.loop_bounds.get(id(loop))
    
    def get_all_loop_bounds(self) -> Dict[int, LoopBound]:
        """Get all loop bounds."""
        return self.loop_bounds.copy()
    
    def get_max_nesting_depth(self) -> int:
        """Get the maximum loop nesting depth in the module."""
        # This would require tracking during analysis
        # For now, return a placeholder
        return 0
    
    # ========================================================================
    # Nested Loop Analysis
    # ========================================================================
    
    def calculate_total_iterations(self, loop_chain: list) -> int:
        """
        Calculate total iterations for a chain of nested loops.
        loop_chain is a list of ForStmt nodes from outer to inner.
        """
        total = 1
        for loop in loop_chain:
            bound = self.get_loop_bound(loop)
            if bound:
                total *= bound.max_iterations
            else:
                return -1  # Unbounded
        return total
    
    # ========================================================================
    # Error Reporting
    # ========================================================================
    
    def _error(self, code: str, message: str, span: SourceSpan):
        """Report an error."""
        self.diag.error(code, message, span.start_line, span.start_col,
                       filename=f"<{self.current_module_name}>")
    
    def _warning(self, code: str, message: str, span: SourceSpan):
        """Report a warning."""
        self.diag.warning(code, message, span.start_line, span.start_col,
                         filename=f"<{self.current_module_name}>")


# ============================================================================
# Convenience Functions
# ============================================================================

def analyze_loops(module: Module, diag: DiagnosticEngine,
                 const_eval: ConstantEvaluator,
                 module_scope: Scope) -> LoopAnalyzer:
    """
    Convenience function to analyze all loops in a module.
    Returns the analyzer for querying loop bounds.
    """
    analyzer = LoopAnalyzer(diag, const_eval, module_scope)
    analyzer.analyze(module)
    return analyzer
