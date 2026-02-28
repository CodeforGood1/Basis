"""
BASIS Resource Analysis
Statically computes and validates resource usage per function.
Analyzes stack, heap, and recursion at compile time.
"""

from typing import Dict, Set, Optional, List, Tuple
from dataclasses import dataclass
from ast_defs import *
from diagnostics import DiagnosticEngine
from sema import Scope, Symbol
from typecheck import TypeChecker, BasisType, IntType, FloatType, BoolType, PointerType, ArrayType, StructType
from consteval import ConstantEvaluator, IntConstant
from loop_analysis import LoopAnalyzer


# ============================================================================
# Resource Metadata
# ============================================================================

@dataclass
class FunctionResource:
    """Resource usage metadata for a function."""
    stack_bytes: int
    heap_bytes: int
    recursion_depth: Optional[int]  # None if non-recursive
    
    def __repr__(self):
        rec = f", recursion_depth={self.recursion_depth}" if self.recursion_depth else ""
        return f"FunctionResource(stack={self.stack_bytes}B, heap={self.heap_bytes}B{rec})"


# ============================================================================
# Call Graph for Recursion Detection
# ============================================================================

class CallGraph:
    """Builds and analyzes function call graph for recursion detection."""
    
    def __init__(self):
        # Function name -> set of called function names
        self.calls: Dict[str, Set[str]] = {}
        
        # Detected cycles
        self.cycles: List[List[str]] = []
    
    def add_call(self, caller: str, callee: str):
        """Record a function call."""
        if caller not in self.calls:
            self.calls[caller] = set()
        self.calls[caller].add(callee)
    
    def detect_cycles(self) -> List[List[str]]:
        """Detect all cycles in the call graph."""
        visited = set()
        rec_stack = set()
        self.cycles = []
        
        def dfs(node: str, path: List[str]):
            # Prevent infinite recursion on nodes not in call graph
            if node not in self.calls and node not in visited:
                visited.add(node)
                return
            
            if node in rec_stack:
                # Found a cycle
                cycle_start = path.index(node)
                cycle = path[cycle_start:]
                self.cycles.append(cycle)
                return
            
            if node in visited:
                return
            
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            if node in self.calls:
                for callee in self.calls[node]:
                    dfs(callee, path[:])
            
            rec_stack.remove(node)
        
        for func in self.calls.keys():
            if func not in visited:
                dfs(func, [])
        
        return self.cycles
    
    def is_recursive(self, func_name: str) -> bool:
        """Check if a function is involved in recursion."""
        for cycle in self.cycles:
            if func_name in cycle:
                return True
        return False
    
    def get_cycle_for_function(self, func_name: str) -> Optional[List[str]]:
        """Get the recursion cycle containing this function."""
        for cycle in self.cycles:
            if func_name in cycle:
                return cycle
        return None


# ============================================================================
# Resource Analyzer
# ============================================================================

class ResourceAnalyzer:
    """
    Analyzes stack, heap, and recursion resource usage.
    Computes compile-time bounds for all functions.
    """
    
    def __init__(self, diag_engine: DiagnosticEngine,
                 type_checker: TypeChecker,
                 const_eval: ConstantEvaluator,
                 loop_analyzer: LoopAnalyzer,
                 module_scope: Scope):
        self.diag = diag_engine
        self.type_checker = type_checker
        self.const_eval = const_eval
        self.loop_analyzer = loop_analyzer
        self.module_scope = module_scope
        
        # Function resources: name -> FunctionResource
        self.resources: Dict[str, FunctionResource] = {}
        
        # Call graph for recursion detection
        self.call_graph = CallGraph()
        
        # Current analysis context
        self.current_function: Optional[str] = None
        self.current_module_name: str = ""
        
        # Bounded parameters for current function
        self.bounded_params: Dict[str, int] = {}
        
        # Track local variable values (for allocation size tracking)
        self.tracked_local_values: Dict[str, int] = {}
        
        # Track if we're inside a loop
        self.current_loop_bound: Optional[int] = None
    
    # ========================================================================
    # Main Entry Point
    # ========================================================================
    
    def analyze(self, module: Module) -> bool:
        """
        Analyze all functions in the module.
        Returns True if successful (no errors).
        """
        self.current_module_name = module.name
        
        # First pass: build call graph and extract annotations
        for decl in module.declarations:
            if isinstance(decl, FunctionDecl):
                self._build_call_graph(decl)
        
        # Detect recursion cycles
        self.call_graph.detect_cycles()
        
        # Second pass: analyze resources
        for decl in module.declarations:
            if isinstance(decl, FunctionDecl):
                self._analyze_function(decl)
        
        return not self.diag.has_errors()
    
    # ========================================================================
    # Call Graph Building
    # ========================================================================
    
    def _build_call_graph(self, func: FunctionDecl):
        """Build call graph for a function."""
        self.current_function = func.name
        
        if func.body:
            self._extract_calls(func.body)
        
        self.current_function = None
    
    def _extract_calls(self, node):
        """Extract function calls from AST node."""
        if isinstance(node, CallExpr):
            if isinstance(node.callee, IdentifierExpr):
                callee_name = node.callee.name
                assert self.current_function is not None
                self.call_graph.add_call(self.current_function, callee_name)
            for arg in node.arguments:
                self._extract_calls(arg)
            return
        
        # Recursively traverse statements
        if isinstance(node, Block):
            for stmt in node.statements:
                self._extract_calls(stmt)
        elif isinstance(node, LetDecl):
            if node.initializer:
                self._extract_calls(node.initializer)
        elif isinstance(node, ForStmt):
            self._extract_calls(node.body)
        elif isinstance(node, WhileStmt):
            self._extract_calls(node.condition)
            self._extract_calls(node.body)
        elif isinstance(node, IfStmt):
            self._extract_calls(node.condition)
            self._extract_calls(node.then_block)
            for elif_branch in node.elif_branches:
                self._extract_calls(elif_branch.condition)
                self._extract_calls(elif_branch.block)
            if node.else_block:
                self._extract_calls(node.else_block)
        elif isinstance(node, ExprStmt):
            self._extract_calls(node.expression)
        elif isinstance(node, ReturnStmt):
            if node.value:
                self._extract_calls(node.value)
        # Expressions
        elif isinstance(node, BinaryExpr):
            self._extract_calls(node.left)
            self._extract_calls(node.right)
        elif isinstance(node, UnaryExpr):
            self._extract_calls(node.operand)
        elif isinstance(node, AssignmentExpr):
            self._extract_calls(node.target)
            self._extract_calls(node.value)
        elif isinstance(node, IndexExpr):
            self._extract_calls(node.base)
            self._extract_calls(node.index)
        elif isinstance(node, FieldAccessExpr):
            self._extract_calls(node.base)
        elif isinstance(node, CastExpr):
            self._extract_calls(node.expression)
        elif isinstance(node, AddressOfExpr):
            self._extract_calls(node.operand)
        elif isinstance(node, DereferenceExpr):
            self._extract_calls(node.operand)
    
    # ========================================================================
    # Function Analysis
    # ========================================================================
    
    def _analyze_function(self, func: FunctionDecl):
        """Analyze resource usage for a function."""
        self.current_function = func.name
        
        # Extract bounded parameters
        self.bounded_params.clear()
        self.tracked_local_values.clear()
        for param in func.params:
            if param.name.endswith('_bounded'):
                self.bounded_params[param.name] = 1000  # Demo value
        
        # Check for recursion
        is_recursive = self.call_graph.is_recursive(func.name)
        recursion_depth = None
        
        if is_recursive:
            # Must have @recursion annotation
            recursion_depth = self._get_recursion_annotation(func)
            if recursion_depth is None:
                cycle = self.call_graph.get_cycle_for_function(func.name)
                cycle_str = " -> ".join(cycle + [cycle[0]]) if cycle else func.name
                self._error("E_MISSING_RECURSION_ANNOTATION",
                           f"recursive function '{func.name}' missing @recursion(max=N) annotation (cycle: {cycle_str})",
                           func.span)
                # Continue analysis with dummy value to find other errors
                recursion_depth = 1
        
        # Calculate stack usage
        stack_bytes = 0
        if func.body:
            stack_bytes = self._calculate_stack_usage(func)
        
        # Calculate heap usage
        # Skip for allocation wrapper functions (they forward to malloc, heap tracked at call site)
        heap_bytes = 0
        alloc_wrappers = {"alloc_bytes", "alloc_u8", "alloc_i32", "alloc_u32", "alloc_i64",
                          "alloc_zeroed", "free_bytes", "mem_copy", "mem_zero"}
        if func.body and func.name not in alloc_wrappers:
            heap_bytes = self._calculate_heap_usage(func.body)
        
        # Adjust for recursion
        if is_recursive and recursion_depth:
            stack_bytes *= recursion_depth
            heap_bytes *= recursion_depth
        
        # Store results
        self.resources[func.name] = FunctionResource(
            stack_bytes=stack_bytes,
            heap_bytes=heap_bytes,
            recursion_depth=recursion_depth
        )
        
        # Validate @stack(N) budget if annotated
        stack_budget = self._get_stack_annotation(func)
        if stack_budget is not None and stack_bytes > stack_budget:
            self._warning("W_STACK_BUDGET_EXCEEDED",
                         f"function '{func.name}' uses {stack_bytes}B stack, "
                         f"exceeds @stack({stack_budget}) budget",
                         func.span)
        
        self.current_function = None
        self.bounded_params.clear()
    
    def _get_recursion_annotation(self, func: FunctionDecl) -> Optional[int]:
        """Extract recursion depth from @recursion annotation."""
        for annotation in func.annotations:
            if annotation.name == "recursion":
                # Support @recursion(max=N) or @recursion(N)
                arg = annotation.arguments.get('max') or annotation.arguments.get('value')
                if arg is None:
                    self._error("E_INVALID_RECURSION_ANNOTATION",
                               "@recursion annotation requires argument: @recursion(max=N)",
                               annotation.span)
                    return None
                
                try:
                    value = self.const_eval.eval_constant(arg)
                    if isinstance(value, IntConstant):
                        if value.value <= 0:
                            self._error("E_INVALID_RECURSION_ANNOTATION",
                                       f"@recursion max depth must be positive, got {value.value}",
                                       annotation.span)
                            return None
                        return value.value
                    else:
                        self._error("E_INVALID_RECURSION_ANNOTATION",
                                   "@recursion max must be an integer constant",
                                   annotation.span)
                        return None
                except (ValueError, TypeError):
                    self._error("E_INVALID_RECURSION_ANNOTATION",
                               "@recursion max must be a compile-time constant",
                               annotation.span)
                    return None
        
        return None
    
    def _get_stack_annotation(self, func: FunctionDecl) -> Optional[int]:
        """Extract stack budget from @stack annotation."""
        for annotation in func.annotations:
            if annotation.name == "stack":
                arg = annotation.arguments.get('value')
                if arg is None:
                    self._error("E_INVALID_STACK_ANNOTATION",
                               "@stack annotation requires argument: @stack(N)",
                               annotation.span)
                    return None
                try:
                    value = self.const_eval.eval_constant(arg)
                    if isinstance(value, IntConstant):
                        return value.value
                except (ValueError, TypeError):
                    pass
                return None
        return None
    
    # ========================================================================
    # Stack Usage Calculation
    # ========================================================================
    
    def _calculate_stack_usage(self, func: FunctionDecl) -> int:
        """Calculate stack usage for a function."""
        total = 0
        
        # Add parameter sizes
        for param in func.params:
            param_type = self.type_checker._resolve_type(param.type)
            if param_type:
                total += self._sizeof(param_type)
        
        # Add local variable sizes
        if func.body:
            total += self._calculate_block_stack(func.body)
        
        return total
    
    def _calculate_block_stack(self, block: Block) -> int:
        """Calculate stack usage for a block."""
        total = 0
        
        for stmt in block.statements:
            if isinstance(stmt, LetDecl):
                var_type = self.type_checker._resolve_type(stmt.type)
                if var_type:
                    total += self._sizeof(var_type)
            
            elif isinstance(stmt, Block):
                total += self._calculate_block_stack(stmt)
            
            elif isinstance(stmt, IfStmt):
                # Take maximum of branches
                then_stack = self._calculate_block_stack(stmt.then_block)
                max_branch = then_stack
                
                for elif_branch in stmt.elif_branches:
                    elif_stack = self._calculate_block_stack(elif_branch.block)
                    max_branch = max(max_branch, elif_stack)
                
                if stmt.else_block:
                    else_stack = self._calculate_block_stack(stmt.else_block)
                    max_branch = max(max_branch, else_stack)
                
                total += max_branch
            
            elif isinstance(stmt, ForStmt):
                # Iterator variable
                total += 4  # Assume i32
                # Body stack
                total += self._calculate_block_stack(stmt.body)
            
            elif isinstance(stmt, WhileStmt):
                # While loop body stack
                total += self._calculate_block_stack(stmt.body)
        
        return total
    
    def _sizeof(self, typ: BasisType) -> int:
        """Calculate size of a type in bytes."""
        if isinstance(typ, IntType):
            return typ.bits // 8
        elif isinstance(typ, FloatType):
            return typ.bits // 8
        elif isinstance(typ, BoolType):
            return 1
        elif isinstance(typ, PointerType):
            return 4  # 32-bit pointers (typical embedded target)
        elif isinstance(typ, ArrayType):
            element_size = self._sizeof(typ.element)
            # Use the known size from type if available, otherwise assume 1 element
            array_count = typ.size if typ.size is not None else 1
            return element_size * array_count
        elif isinstance(typ, StructType):
            # Sum of field sizes (ignoring padding for now)
            total = 0
            for field_type in typ.fields.values():
                total += self._sizeof(field_type)
            return total
        else:
            return 0
    
    # ========================================================================
    # Heap Usage Calculation
    # ========================================================================
    
    def _calculate_heap_usage(self, node) -> int:
        """Calculate heap usage in a code block."""
        total = 0
        
        if isinstance(node, Block):
            for stmt in node.statements:
                total += self._calculate_heap_usage(stmt)
        
        elif isinstance(node, ForStmt):
            # Get loop bound
            loop_bound = self.loop_analyzer.get_loop_bound(node)
            if loop_bound:
                # Save current loop context
                prev_loop_bound = self.current_loop_bound
                self.current_loop_bound = loop_bound.max_iterations
                
                body_heap = self._calculate_heap_usage(node.body)
                total += body_heap * loop_bound.max_iterations
                
                self.current_loop_bound = prev_loop_bound
            else:
                # Unbounded loop - check for allocations
                if self._contains_allocation(node.body):
                    self._error("E_UNBOUNDED_HEAP",
                               "heap allocation in loop with unbounded iteration count",
                               node.span)
        
        elif isinstance(node, WhileStmt):
            # Use max_iterations from @bounded annotation if available
            if node.max_iterations is not None:
                prev_loop_bound = self.current_loop_bound
                self.current_loop_bound = node.max_iterations
                
                body_heap = self._calculate_heap_usage(node.body)
                total += body_heap * node.max_iterations
                
                self.current_loop_bound = prev_loop_bound
            else:
                if self._contains_allocation(node.body):
                    self._error("E_UNBOUNDED_HEAP",
                               "heap allocation in while loop without @bounded annotation",
                               node.span)
        
        elif isinstance(node, IfStmt):
            # Take maximum of branches
            then_heap = self._calculate_heap_usage(node.then_block)
            max_branch = then_heap
            
            for elif_branch in node.elif_branches:
                elif_heap = self._calculate_heap_usage(elif_branch.block)
                max_branch = max(max_branch, elif_heap)
            
            if node.else_block:
                else_heap = self._calculate_heap_usage(node.else_block)
                max_branch = max(max_branch, else_heap)
            
            total += max_branch
        
        elif isinstance(node, ExprStmt):
            total += self._calculate_expr_heap(node.expression)
        
        elif isinstance(node, LetDecl):
            if node.initializer:
                total += self._calculate_expr_heap(node.initializer)
                # Track variable value if it's a constant integer
                init_val = self._evaluate_alloc_size(node.initializer)
                if init_val is not None:
                    self.tracked_local_values[node.name] = init_val
        
        elif isinstance(node, ReturnStmt):
            if node.value:
                total += self._calculate_expr_heap(node.value)
        
        return total
    
    def _calculate_expr_heap(self, expr: Expression) -> int:
        """Calculate heap usage in an expression."""
        total = 0
        
        if isinstance(expr, CallExpr):
            # Check if it's an alloc call
            if isinstance(expr.callee, IdentifierExpr):
                callee_name = expr.callee.name
                
                # Recognize allocation functions
                if callee_name == "alloc" and len(expr.arguments) >= 2:
                    # alloc(type, size)
                    size_arg = expr.arguments[1]
                    alloc_size = self._evaluate_alloc_size(size_arg)
                    
                    if alloc_size is not None:
                        total += alloc_size
                    else:
                        self._error("E_UNBOUNDED_HEAP",
                                   "allocation size must be a compile-time constant or bounded parameter",
                                   size_arg.span)
                
                elif callee_name in ("alloc_bytes", "alloc_u8", "malloc") and len(expr.arguments) >= 1:
                    # alloc_bytes(size), alloc_u8(count), malloc(size) - 1 byte per element
                    size_arg = expr.arguments[0]
                    alloc_size = self._evaluate_alloc_size(size_arg)
                    
                    if alloc_size is not None:
                        total += alloc_size
                    else:
                        self._error("E_UNBOUNDED_HEAP",
                                   "allocation size must be a compile-time constant or bounded parameter",
                                   size_arg.span)
                
                elif callee_name == "alloc_i32" and len(expr.arguments) >= 1:
                    # alloc_i32(count) - 4 bytes per element
                    count_arg = expr.arguments[0]
                    alloc_count = self._evaluate_alloc_size(count_arg)
                    
                    if alloc_count is not None:
                        total += alloc_count * 4  # 4 bytes per i32
                    else:
                        self._error("E_UNBOUNDED_HEAP",
                                   "allocation size must be a compile-time constant or bounded parameter",
                                   count_arg.span)
                
                elif callee_name == "alloc_u32" and len(expr.arguments) >= 1:
                    count_arg = expr.arguments[0]
                    alloc_count = self._evaluate_alloc_size(count_arg)
                    if alloc_count is not None:
                        total += alloc_count * 4
                    else:
                        self._error("E_UNBOUNDED_HEAP",
                                   "allocation size must be a compile-time constant or bounded parameter",
                                   count_arg.span)
                
                elif callee_name == "alloc_i64" and len(expr.arguments) >= 1:
                    count_arg = expr.arguments[0]
                    alloc_count = self._evaluate_alloc_size(count_arg)
                    if alloc_count is not None:
                        total += alloc_count * 8
                    else:
                        self._error("E_UNBOUNDED_HEAP",
                                   "allocation size must be a compile-time constant or bounded parameter",
                                   count_arg.span)
                
                elif callee_name == "alloc_zeroed" and len(expr.arguments) >= 1:
                    size_arg = expr.arguments[0]
                    alloc_size = self._evaluate_alloc_size(size_arg)
                    if alloc_size is not None:
                        total += alloc_size
                    else:
                        self._error("E_UNBOUNDED_HEAP",
                                   "allocation size must be a compile-time constant or bounded parameter",
                                   size_arg.span)
                
                elif callee_name in self.resources:
                    # Regular function call - add callee's heap usage
                    total += self.resources[callee_name].heap_bytes
        
        elif isinstance(expr, BinaryExpr):
            total += self._calculate_expr_heap(expr.left)
            total += self._calculate_expr_heap(expr.right)
        
        elif isinstance(expr, UnaryExpr):
            total += self._calculate_expr_heap(expr.operand)
        
        elif isinstance(expr, AssignmentExpr):
            total += self._calculate_expr_heap(expr.target)
            total += self._calculate_expr_heap(expr.value)
        
        return total
    
    def _evaluate_alloc_size(self, expr: Expression) -> Optional[int]:
        """Evaluate allocation size expression."""
        # Direct literal - always works
        if isinstance(expr, LiteralExpr) and expr.kind == 'int':
            return parse_int_literal(expr.value)
        
        # Cast expression - extract inner value
        if isinstance(expr, CastExpr):
            return self._evaluate_alloc_size(expr.expression)
        
        # Check if it's a bounded parameter or tracked local
        if isinstance(expr, IdentifierExpr):
            if expr.name in self.bounded_params:
                return self.bounded_params[expr.name]
            # Check if we tracked this variable's value
            if expr.name in self.tracked_local_values:
                return self.tracked_local_values[expr.name]
            # Try const evaluation only for identifiers (const decls)
            if expr.name in self.const_eval.const_values:
                val = self.const_eval.const_values[expr.name]
                if isinstance(val, IntConstant):
                    return val.value
        
        # Binary expression - try to evaluate
        if isinstance(expr, BinaryExpr):
            left_val = self._evaluate_alloc_size(expr.left)
            right_val = self._evaluate_alloc_size(expr.right)
            if left_val is not None and right_val is not None:
                if expr.operator == '+':
                    return left_val + right_val
                elif expr.operator == '-':
                    return left_val - right_val
                elif expr.operator == '*':
                    return left_val * right_val
                elif expr.operator == '/':
                    return left_val // right_val
        
        return None
    
    def _contains_allocation(self, node) -> bool:
        """Check if a node contains any heap allocation."""
        if isinstance(node, Block):
            for stmt in node.statements:
                if self._contains_allocation(stmt):
                    return True
        
        elif isinstance(node, ExprStmt):
            return self._expr_contains_allocation(node.expression)
        
        elif isinstance(node, LetDecl):
            if node.initializer:
                return self._expr_contains_allocation(node.initializer)
        
        elif isinstance(node, ReturnStmt):
            if node.value:
                return self._expr_contains_allocation(node.value)
        
        elif isinstance(node, IfStmt):
            if self._contains_allocation(node.then_block):
                return True
            for elif_branch in node.elif_branches:
                if self._contains_allocation(elif_branch.block):
                    return True
            if node.else_block and self._contains_allocation(node.else_block):
                return True
        
        elif isinstance(node, ForStmt):
            return self._contains_allocation(node.body)
        
        elif isinstance(node, WhileStmt):
            return self._contains_allocation(node.body)
        
        return False
    
    _ALLOC_FUNCTIONS = {"alloc", "alloc_bytes", "alloc_u8", "alloc_i32",
                         "alloc_u32", "alloc_i64", "alloc_zeroed", "malloc"}

    def _expr_contains_allocation(self, expr: Expression) -> bool:
        """Check if expression contains allocation."""
        if isinstance(expr, CallExpr):
            if isinstance(expr.callee, IdentifierExpr) and expr.callee.name in self._ALLOC_FUNCTIONS:
                return True
        
        elif isinstance(expr, BinaryExpr):
            return self._expr_contains_allocation(expr.left) or self._expr_contains_allocation(expr.right)
        
        elif isinstance(expr, UnaryExpr):
            return self._expr_contains_allocation(expr.operand)
        
        elif isinstance(expr, AssignmentExpr):
            return self._expr_contains_allocation(expr.target) or self._expr_contains_allocation(expr.value)
        
        return False
    
    # ========================================================================
    # Query Interface
    # ========================================================================
    
    def get_resource(self, func_name: str) -> Optional[FunctionResource]:
        """Get resource metadata for a function."""
        return self.resources.get(func_name)
    
    def get_all_resources(self) -> Dict[str, FunctionResource]:
        """Get all function resources."""
        return self.resources.copy()
    
    # ========================================================================
    # Error Reporting
    # ========================================================================
    
    def _error(self, code: str, message: str, span: SourceSpan):
        """Report an error."""
        self.diag.error(code, message, span.start_line, span.start_col,
                       filename=f"<{self.current_module_name}>")
    
    def _warning(self, code: str, message: str, span: SourceSpan):
        """Report a warning."""
        self.diag.report('warning', code, message, span.start_line, span.start_col,
                        filename=f"<{self.current_module_name}>")


# ============================================================================
# Convenience Functions
# ============================================================================

def analyze_resources(module: Module, diag: DiagnosticEngine,
                     type_checker: TypeChecker,
                     const_eval: ConstantEvaluator,
                     loop_analyzer: LoopAnalyzer,
                     module_scope: Scope) -> ResourceAnalyzer:
    """
    Convenience function to analyze resources in a module.
    Returns the analyzer for querying resource usage.
    """
    analyzer = ResourceAnalyzer(diag, type_checker, const_eval, loop_analyzer, module_scope)
    analyzer.analyze(module)
    return analyzer
