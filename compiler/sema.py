"""
BASIS Semantic Analysis - Name Resolution Phase
Builds symbol tables, resolves identifiers, enforces visibility rules.
Does NOT perform type checking or resource analysis.
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from ast_defs import *
from diagnostics import DiagnosticEngine


# ============================================================================
# Symbol Representation
# ============================================================================

@dataclass
class Symbol:
    """Represents a declared symbol in the program."""
    name: str
    kind: str  # 'function', 'struct', 'const', 'let', 'param', 'module', 'extern_static'
    decl_node: ASTNode  # The declaration node
    visibility: Optional[str]  # 'public', 'private', or None (default private)
    scope_level: int  # 0 = module, 1+ = nested scopes
    
    def is_public(self) -> bool:
        """Check if this symbol is publicly visible."""
        return self.visibility == 'public'
    
    def is_accessible_from(self, current_module: bool) -> bool:
        """Check if symbol is accessible from given context."""
        if current_module:
            return True  # All symbols accessible within same module
        return self.is_public()


# ============================================================================
# Scope Management
# ============================================================================

class Scope:
    """Represents a lexical scope containing symbol bindings."""
    
    def __init__(self, parent: Optional['Scope'] = None, level: int = 0, kind: str = 'module'):
        self.parent = parent
        self.level = level
        self.kind = kind  # 'module', 'function', 'block'
        self.symbols: Dict[str, Symbol] = {}
    
    def define(self, name: str, symbol: Symbol) -> bool:
        """
        Define a symbol in this scope.
        Returns False if already defined in this scope.
        """
        if name in self.symbols:
            return False
        self.symbols[name] = symbol
        return True
    
    def lookup_local(self, name: str) -> Optional[Symbol]:
        """Look up symbol only in this scope."""
        return self.symbols.get(name)
    
    def lookup(self, name: str) -> Optional[Symbol]:
        """Look up symbol in this scope and parent scopes."""
        if name in self.symbols:
            return self.symbols[name]
        if self.parent:
            return self.parent.lookup(name)
        return None
    
    def get_function_scope(self) -> Optional['Scope']:
        """Find the nearest enclosing function scope."""
        if self.kind == 'function':
            return self
        if self.parent:
            return self.parent.get_function_scope()
        return None


# ============================================================================
# Module Registry (stub for imports)
# ============================================================================

class ModuleRegistry:
    """Tracks available modules for import validation."""
    
    def __init__(self):
        # Stub: In real implementation, this would scan filesystem or manifest
        # For now, we'll just track modules we've analyzed
        self.modules: Dict[str, Dict[str, Symbol]] = {}
    
    def register_module(self, name: str, exports: Dict[str, Symbol]):
        """Register a module's public exports."""
        public_exports = {k: v for k, v in exports.items() if v.is_public()}
        self.modules[name] = public_exports
    
    def get_module(self, name: str) -> Optional[Dict[str, Symbol]]:
        """Get public exports from a module."""
        return self.modules.get(name)
    
    def module_exists(self, name: str) -> bool:
        """Check if module exists (stub: always true for now)."""
        # In real implementation, check filesystem or manifest
        # For now, assume all imports are valid modules
        return True
    
    def get_symbol(self, module_name: str, symbol_name: str) -> Optional[Symbol]:
        """Get a specific symbol from a module."""
        module = self.get_module(module_name)
        if module:
            return module.get(symbol_name)
        return None


# ============================================================================
# Semantic Analyzer
# ============================================================================

class SemanticAnalyzer:
    """
    Performs name resolution for BASIS programs.
    Builds symbol tables, resolves identifiers, enforces visibility.
    """
    
    def __init__(self, diag_engine: DiagnosticEngine, module_registry: Optional[ModuleRegistry] = None):
        self.diag = diag_engine
        self.registry = module_registry or ModuleRegistry()
        
        # Scope stack
        self.current_scope: Optional[Scope] = None
        self.module_scope: Optional[Scope] = None
        
        # Current module name
        self.current_module_name: str = ""
        
        # Track imported symbols
        self.imported_symbols: Dict[str, Symbol] = {}
        
        # For error recovery: track if we're in a valid context
        self.in_function = False
        self.in_loop = False
        
        # Dead code analysis: track declared and called functions
        self._declared_functions: Set[str] = set()
        self._called_functions: Set[str] = set()
        self._extern_functions: Set[str] = set()
    
    # ========================================================================
    # Main Entry Point
    # ========================================================================
    
    def analyze(self, module: Module) -> bool:
        """
        Analyze a module and resolve all names.
        Returns True if successful (no errors).
        """
        self.current_module_name = module.name
        
        # Create module scope
        self.module_scope = Scope(parent=None, level=0, kind='module')
        self.current_scope = self.module_scope
        
        # First pass: collect all top-level declarations
        self._collect_declarations(module)
        
        # Second pass: resolve names in declarations
        for decl in module.declarations:
            self._analyze_declaration(decl)
        
        # Register module exports
        self.registry.register_module(module.name, self.module_scope.symbols)
        
        # Dead code analysis: warn about unused private functions
        self._check_unused_functions(module)
        
        return not self.diag.has_errors()
    
    # ========================================================================
    # Declaration Collection (First Pass)
    # ========================================================================
    
    def _collect_declarations(self, module: Module):
        """First pass: collect all top-level declarations into module scope."""
        for decl in module.declarations:
            if isinstance(decl, ImportDecl):
                self._collect_import(decl)
            elif isinstance(decl, FunctionDecl):
                self._collect_function(decl)
            elif isinstance(decl, StructDecl):
                self._collect_struct(decl)
            elif isinstance(decl, ConstDecl):
                self._collect_const(decl)
            elif isinstance(decl, ExternStaticDecl):
                self._collect_extern_static(decl)
            # Note: LetDecl not allowed at module level
    
    def _collect_import(self, decl: ImportDecl):
        """Process import declaration."""
        # Validate module exists
        if not self.registry.module_exists(decl.module_name):
            self._error(
                "E_UNKNOWN_MODULE",
                f"unknown module '{decl.module_name}'",
                decl.span
            )
            return
        
        if decl.is_wildcard:
            # import mod::*
            module = self.registry.get_module(decl.module_name)
            if module:
                for name, symbol in module.items():
                    if name in self.imported_symbols:
                        self._error(
                            "E_DUPLICATE_IMPORT",
                            f"symbol '{name}' already imported",
                            decl.span
                        )
                    else:
                        self.imported_symbols[name] = symbol
                        # Also add to module scope for type checker access
                        if self.module_scope:
                            self.module_scope.symbols[name] = symbol
        
        elif decl.items:
            # import mod::{a, b, c}
            for item in decl.items:
                symbol = self.registry.get_symbol(decl.module_name, item)
                if not symbol:
                    self._error(
                        "E_UNKNOWN_SYMBOL",
                        f"symbol '{item}' not found in module '{decl.module_name}'",
                        decl.span
                    )
                elif item in self.imported_symbols:
                    self._error(
                        "E_DUPLICATE_IMPORT",
                        f"symbol '{item}' already imported",
                        decl.span
                    )
                else:
                    self.imported_symbols[item] = symbol
                    # Also add to module scope for type checker access
                    if self.module_scope:
                        self.module_scope.symbols[item] = symbol
        
        else:
            # import mod (module-level import, not used in v1.0)
            pass
    
    def _collect_function(self, decl: FunctionDecl):
        """Collect function declaration."""
        assert self.current_scope is not None, "current_scope should be initialized"
        
        symbol = Symbol(
            name=decl.name,
            kind='function',
            decl_node=decl,
            visibility=decl.visibility or 'private',
            scope_level=0
        )
        
        if not self.current_scope.define(decl.name, symbol):
            existing = self.current_scope.lookup_local(decl.name)
            self._error(
                "E_DUPLICATE_SYMBOL",
                f"duplicate declaration of function '{decl.name}'",
                decl.span,
                note=f"previously declared at {existing.decl_node.span}" if existing else None
            )
        
        self._declared_functions.add(decl.name)
        if not decl.body:
            self._extern_functions.add(decl.name)
    
    def _collect_struct(self, decl: StructDecl):
        """Collect struct declaration."""
        assert self.current_scope is not None, "current_scope should be initialized"
        
        symbol = Symbol(
            name=decl.name,
            kind='struct',
            decl_node=decl,
            visibility=decl.visibility or 'private',
            scope_level=0
        )
        
        if not self.current_scope.define(decl.name, symbol):
            existing = self.current_scope.lookup_local(decl.name)
            self._error(
                "E_DUPLICATE_SYMBOL",
                f"duplicate declaration of struct '{decl.name}'",
                decl.span,
                note=f"previously declared at {existing.decl_node.span}" if existing else None
            )
    
    def _collect_const(self, decl: ConstDecl):
        """Collect const declaration."""
        assert self.current_scope is not None, "current_scope should be initialized"
        
        symbol = Symbol(
            name=decl.name,
            kind='const',
            decl_node=decl,
            visibility=decl.visibility or 'private',
            scope_level=0
        )
        
        if not self.current_scope.define(decl.name, symbol):
            existing = self.current_scope.lookup_local(decl.name)
            self._error(
                "E_DUPLICATE_SYMBOL",
                f"duplicate declaration of const '{decl.name}'",
                decl.span,
                note=f"previously declared at {existing.decl_node.span}" if existing else None
            )
    
    def _collect_extern_static(self, decl: ExternStaticDecl):
        """Collect extern static declaration."""
        assert self.current_scope is not None, "current_scope should be initialized"
        
        symbol = Symbol(
            name=decl.name,
            kind='extern_static',
            decl_node=decl,
            visibility='public',  # extern statics are always public
            scope_level=0
        )
        
        if not self.current_scope.define(decl.name, symbol):
            existing = self.current_scope.lookup_local(decl.name)
            self._error(
                "E_DUPLICATE_SYMBOL",
                f"duplicate declaration of extern static '{decl.name}'",
                decl.span,
                note=f"previously declared at {existing.decl_node.span}" if existing else None
            )
    
    # ========================================================================
    # Declaration Analysis (Second Pass)
    # ========================================================================
    
    def _analyze_declaration(self, decl: Declaration):
        """Analyze a declaration and resolve names within it."""
        if isinstance(decl, ImportDecl):
            # Already handled in first pass
            pass
        
        elif isinstance(decl, FunctionDecl):
            self._analyze_function(decl)
        
        elif isinstance(decl, StructDecl):
            self._analyze_struct(decl)
        
        elif isinstance(decl, ConstDecl):
            self._analyze_const(decl)
        
        elif isinstance(decl, ExternStaticDecl):
            # No names to resolve in extern static (type is just syntax)
            pass
    
    def _analyze_function(self, decl: FunctionDecl):
        """Analyze function declaration."""
        # Create function scope
        func_scope = Scope(parent=self.current_scope, level=1, kind='function')
        prev_scope = self.current_scope
        self.current_scope = func_scope
        
        self.in_function = True
        
        # Add parameters to function scope
        param_names = set()
        for param in decl.params:
            if param.name in param_names:
                self._error(
                    "E_DUPLICATE_PARAM",
                    f"duplicate parameter name '{param.name}'",
                    param.span
                )
            else:
                param_names.add(param.name)
                symbol = Symbol(
                    name=param.name,
                    kind='param',
                    decl_node=param,
                    visibility=None,
                    scope_level=1
                )
                func_scope.define(param.name, symbol)
            
            # Resolve type references in parameter type
            self._resolve_type(param.type)
        
        # Resolve return type
        self._resolve_type(decl.return_type)
        
        # Analyze function body if present (not for extern)
        if decl.body:
            self._analyze_block(decl.body)
        
        self.in_function = False
        self.current_scope = prev_scope
    
    def _analyze_struct(self, decl: StructDecl):
        """Analyze struct declaration."""
        # Check for duplicate field names
        field_names = set()
        for field in decl.fields:
            if field.name in field_names:
                self._error(
                    "E_DUPLICATE_FIELD",
                    f"duplicate field name '{field.name}' in struct '{decl.name}'",
                    field.span
                )
            else:
                field_names.add(field.name)
            
            # Resolve type references in field type
            self._resolve_type(field.type)
    
    def _analyze_const(self, decl: ConstDecl):
        """Analyze const declaration."""
        # Resolve type
        self._resolve_type(decl.type)
        
        # Resolve initializer expression
        self._resolve_expression(decl.value)
    
    # ========================================================================
    # Type Resolution
    # ========================================================================
    
    def _resolve_type(self, type_node: Type):
        """Resolve type references (struct names, etc)."""
        if isinstance(type_node, TypeName):
            # Check if it's a built-in type
            if self._is_builtin_type(type_node.name):
                return
            
            # Check if it's a struct type
            symbol = self._lookup_symbol(type_node.name, type_node.span)
            if symbol and symbol.kind != 'struct':
                self._error(
                    "E_NOT_A_TYPE",
                    f"'{type_node.name}' is not a type",
                    type_node.span
                )
        
        elif isinstance(type_node, PointerType):
            self._resolve_type(type_node.base_type)
        
        elif isinstance(type_node, ArrayType):
            self._resolve_type(type_node.element_type)
            # Resolve size expression
            self._resolve_expression(type_node.size_expr)
        
        elif isinstance(type_node, VolatileType):
            self._resolve_type(type_node.base_type)
    
    def _is_builtin_type(self, name: str) -> bool:
        """Check if name is a built-in type."""
        return name in {
            'void', 'bool',
            'i8', 'i16', 'i32', 'i64',
            'u8', 'u16', 'u32', 'u64',
            'f32', 'f64'
        }
    
    # ========================================================================
    # Statement Analysis
    # ========================================================================
    
    def _analyze_statement(self, stmt: Statement):
        """Analyze a statement."""
        if isinstance(stmt, Block):
            self._analyze_block(stmt)
        
        elif isinstance(stmt, ReturnStmt):
            if not self.in_function:
                self._error(
                    "E_RETURN_OUTSIDE_FUNCTION",
                    "return statement outside function",
                    stmt.span
                )
            if stmt.value:
                self._resolve_expression(stmt.value)
        
        elif isinstance(stmt, IfStmt):
            self._resolve_expression(stmt.condition)
            self._analyze_block(stmt.then_block)
            for elif_branch in stmt.elif_branches:
                self._resolve_expression(elif_branch.condition)
                self._analyze_block(elif_branch.block)
            if stmt.else_block:
                self._analyze_block(stmt.else_block)
        
        elif isinstance(stmt, ForStmt):
            assert self.current_scope is not None, "current_scope should be initialized"
            # Create new scope for loop
            loop_scope = Scope(parent=self.current_scope, level=self.current_scope.level + 1, kind='block')
            prev_scope = self.current_scope
            self.current_scope = loop_scope
            
            prev_in_loop = self.in_loop
            self.in_loop = True
            
            # Define iterator variable
            symbol = Symbol(
                name=stmt.iterator_name,
                kind='let',
                decl_node=stmt,
                visibility=None,
                scope_level=loop_scope.level
            )
            loop_scope.define(stmt.iterator_name, symbol)
            
            # Resolve range expressions
            self._resolve_expression(stmt.range_start)
            self._resolve_expression(stmt.range_end)
            
            # Analyze loop body
            self._analyze_block(stmt.body)
            
            self.in_loop = prev_in_loop
            self.current_scope = prev_scope
        
        elif isinstance(stmt, WhileStmt):
            assert self.current_scope is not None, "current_scope should be initialized"
            loop_scope = Scope(parent=self.current_scope, level=self.current_scope.level + 1, kind='block')
            prev_scope = self.current_scope
            self.current_scope = loop_scope
            
            prev_in_loop = self.in_loop
            self.in_loop = True
            
            # Resolve condition expression
            self._resolve_expression(stmt.condition)
            
            # Analyze loop body
            self._analyze_block(stmt.body)
            
            self.in_loop = prev_in_loop
            self.current_scope = prev_scope
        
        elif isinstance(stmt, BreakStmt):
            if not self.in_loop:
                self._error(
                    "E_BREAK_OUTSIDE_LOOP",
                    "break statement outside loop",
                    stmt.span
                )
        
        elif isinstance(stmt, ContinueStmt):
            if not self.in_loop:
                self._error(
                    "E_CONTINUE_OUTSIDE_LOOP",
                    "continue statement outside loop",
                    stmt.span
                )
        
        elif isinstance(stmt, ExprStmt):
            self._resolve_expression(stmt.expression)
        
        elif isinstance(stmt, LetDecl):
            assert self.current_scope is not None, "current_scope should be initialized"
            # Let declaration as statement
            # Check for duplicate in current scope
            if self.current_scope.lookup_local(stmt.name):
                self._error(
                    "E_DUPLICATE_SYMBOL",
                    f"duplicate declaration of variable '{stmt.name}'",
                    stmt.span
                )
            else:
                symbol = Symbol(
                    name=stmt.name,
                    kind='let',
                    decl_node=stmt,
                    visibility=None,
                    scope_level=self.current_scope.level
                )
                self.current_scope.define(stmt.name, symbol)
            
            # Resolve type
            self._resolve_type(stmt.type)
            
            # Resolve initializer if present
            if stmt.initializer:
                self._resolve_expression(stmt.initializer)
    
    def _analyze_block(self, block: Block):
        """Analyze a block of statements."""
        assert self.current_scope is not None, "current_scope should be initialized"
        # Create new scope for block
        block_scope = Scope(parent=self.current_scope, level=self.current_scope.level + 1, kind='block')
        prev_scope = self.current_scope
        self.current_scope = block_scope
        
        for stmt in block.statements:
            self._analyze_statement(stmt)
        
        self.current_scope = prev_scope
    
    # ========================================================================
    # Expression Analysis
    # ========================================================================
    
    def _resolve_expression(self, expr: Expression):
        """Resolve all identifier references in an expression."""
        if isinstance(expr, IdentifierExpr):
            self._lookup_symbol(expr.name, expr.span)
        
        elif isinstance(expr, LiteralExpr):
            # Literals have no names to resolve
            pass
        
        elif isinstance(expr, BinaryExpr):
            self._resolve_expression(expr.left)
            self._resolve_expression(expr.right)
        
        elif isinstance(expr, UnaryExpr):
            self._resolve_expression(expr.operand)
        
        elif isinstance(expr, CallExpr):
            self._resolve_expression(expr.callee)
            # Track function calls for dead code analysis
            if isinstance(expr.callee, IdentifierExpr):
                self._called_functions.add(expr.callee.name)
            for arg in expr.arguments:
                self._resolve_expression(arg)
        
        elif isinstance(expr, IndexExpr):
            self._resolve_expression(expr.base)
            self._resolve_expression(expr.index)
        
        elif isinstance(expr, FieldAccessExpr):
            self._resolve_expression(expr.base)
            # Note: field name validation happens in type checking phase
        
        elif isinstance(expr, AssignmentExpr):
            self._resolve_expression(expr.target)
            self._resolve_expression(expr.value)
        
        elif isinstance(expr, CastExpr):
            self._resolve_expression(expr.expression)
            self._resolve_type(expr.target_type)
        
        elif isinstance(expr, AddressOfExpr):
            self._resolve_expression(expr.operand)
        
        elif isinstance(expr, DereferenceExpr):
            self._resolve_expression(expr.operand)
        
        elif isinstance(expr, ArrayLiteralExpr):
            for elem in expr.elements:
                self._resolve_expression(elem)
        
        elif isinstance(expr, ArrayRepeatExpr):
            self._resolve_expression(expr.value)
            self._resolve_expression(expr.count)
            if expr.overrides:
                for override in expr.overrides:
                    self._resolve_expression(override.value)
        
        elif isinstance(expr, StructLiteralExpr):
            for field in expr.field_inits:
                self._resolve_expression(field.value)
    
    # ========================================================================
    # Symbol Lookup
    # ========================================================================
    
    def _lookup_symbol(self, name: str, span: SourceSpan) -> Optional[Symbol]:
        """
        Look up a symbol by name.
        Checks current scope, parent scopes, and imported symbols.
        Reports error if not found.
        """
        assert self.current_scope is not None, "current_scope should be initialized"
        # Check local scopes
        symbol = self.current_scope.lookup(name)
        if symbol:
            return symbol
        
        # Check imported symbols
        if name in self.imported_symbols:
            return self.imported_symbols[name]
        
        # Not found
        self._error(
            "E_UNDEFINED_SYMBOL",
            f"undefined symbol '{name}'",
            span
        )
        return None
    
    # ========================================================================
    # Error Reporting
    # ========================================================================
    
    def _error(self, code: str, message: str, span: SourceSpan, note: Optional[str] = None):
        """Report a semantic error."""
        self.diag.error(
            code,
            message,
            span.start_line,
            span.start_col,
            length=1,
            filename=f"<{self.current_module_name}>"
        )
        if note:
            self.diag.report(
                'note',
                code,
                note,
                span.start_line,
                span.start_col,
                length=1,
                filename=f"<{self.current_module_name}>"
            )
    
    def _check_unused_functions(self, module: Module):
        """Warn about private functions that are never called."""
        # Skip 'main' — it's the entry point
        entry_points = {'main'}
        
        for name in self._declared_functions:
            if name in entry_points:
                continue
            if name in self._extern_functions:
                continue
            if name in self._called_functions:
                continue
            
            # Check if function is public (exported)
            symbol = self.module_scope.lookup_local(name) if self.module_scope else None
            if symbol and symbol.is_public():
                continue
            
            # Private, non-extern, non-called — warn
            if symbol:
                self.diag.report(
                    'warning',
                    'W_UNUSED_FUNCTION',
                    f"function '{name}' is declared but never called",
                    symbol.decl_node.span.start_line,
                    symbol.decl_node.span.start_col,
                    length=1,
                    filename=f"<{self.current_module_name}>"
                )


# ============================================================================
# Convenience Function
# ============================================================================

def analyze_module(module: Module, diag: DiagnosticEngine, registry: Optional[ModuleRegistry] = None) -> bool:
    """
    Convenience function to analyze a module.
    Returns True if analysis succeeds (no errors).
    """
    analyzer = SemanticAnalyzer(diag, registry)
    return analyzer.analyze(module)
