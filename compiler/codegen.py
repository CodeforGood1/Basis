"""
BASIS C Code Generator
Lowers BASIS AST directly to C99 code.
"""

from typing import List, Optional
from ast_defs import *


class CCodeGenerator:
    """Generates C99 code from BASIS AST."""
    
    # Runtime helper definitions keyed by function name
    RUNTIME_HELPERS = {
        'print_str': 'static void print_str(const char* s) { printf("%s", s); }',
        'print_i8':  'static void print_i8(int8_t x) { printf("%d", (int)x); }',
        'print_i16': 'static void print_i16(int16_t x) { printf("%d", (int)x); }',
        'print_i32': 'static void print_i32(int32_t x) { printf("%d", x); }',
        'print_i64': 'static void print_i64(int64_t x) { printf("%lld", (long long)x); }',
        'print_u8':  'static void print_u8(uint8_t x) { printf("%u", (unsigned)x); }',
        'print_u16': 'static void print_u16(uint16_t x) { printf("%u", (unsigned)x); }',
        'print_u32': 'static void print_u32(uint32_t x) { printf("%u", x); }',
        'print_u64': 'static void print_u64(uint64_t x) { printf("%llu", (unsigned long long)x); }',
        'print_f32': 'static void print_f32(float x) { printf("%g", (double)x); }',
        'print_f64': 'static void print_f64(double x) { printf("%g", x); }',
        'print_bool':'static void print_bool(bool x) { printf("%s", x ? "true" : "false"); }',
        'print_char':'static void print_char(char c) { printf("%c", c); }',
        'print_ptr': 'static void print_ptr(void* p) { printf("%p", p); }',
        'print_int': 'static void print_int(int32_t x) { print_i32(x); }',
        'print_uint':'static void print_uint(uint32_t x) { print_u32(x); }',
        'read_i32':  'static int32_t read_i32(void) { int32_t x; scanf("%d", &x); return x; }',
        'read_i64':  'static int64_t read_i64(void) { int64_t x; scanf("%lld", (long long*)&x); return x; }',
        'read_u32':  'static uint32_t read_u32(void) { uint32_t x; scanf("%u", &x); return x; }',
        'read_u64':  'static uint64_t read_u64(void) { uint64_t x; scanf("%llu", (unsigned long long*)&x); return x; }',
        'read_f32':  'static float read_f32(void) { float x; scanf("%f", &x); return x; }',
        'read_f64':  'static double read_f64(void) { double x; scanf("%lf", &x); return x; }',
        'read_char': 'static char read_char(void) { char c; scanf(" %c", &c); return c; }',
        'read_str':  'static void read_str(char* buf, int32_t max_len) { scanf("%*s"); fgets(buf, max_len, stdin); }',
        'read_line': 'static void read_line(char* buf, int32_t max_len) { int c; while ((c = getchar()) == \'\\n\' || c == \'\\r\'); ungetc(c, stdin); fgets(buf, max_len, stdin); int len = strlen(buf); if (len > 0 && buf[len-1] == \'\\n\') buf[len-1] = \'\\0\'; }',
    }
    
    # Dependencies: some helpers call others
    HELPER_DEPS = {
        'print_int': {'print_i32'},
        'print_uint': {'print_u32'},
    }
    
    def __init__(self):
        self.output: List[str] = []
        self.indent_level = 0
        self._bounds_check_counter = 0  # For unique temp variable names
    
    # ========================================================================
    # Main Entry Point
    # ========================================================================
    
    def generate(self, module: Module) -> str:
        """Generate C code for a module."""
        self.output = []
        self.indent_level = 0
        
        # Emit headers
        self._emit_line("#include <stdint.h>")
        self._emit_line("#include <stdlib.h>")
        self._emit_line("#include <stdbool.h>")
        self._emit_line("#include <stdio.h>")
        self._emit_line("#include <string.h>")
        self._emit_line("#ifndef BASIS_INTERRUPT")
        self._emit_line("#define BASIS_INTERRUPT")
        self._emit_line("#endif")
        self._emit_line("")
        
        # Scan AST for referenced runtime helpers and emit only those used
        used_helpers = self._collect_used_helpers(module)
        needs_bounds_check = self._needs_bounds_check(module)
        
        if used_helpers:
            self._emit_line("// BASIS runtime helpers")
            for name in self.RUNTIME_HELPERS:
                if name in used_helpers:
                    self._emit_line(self.RUNTIME_HELPERS[name])
            self._emit_line("")
        
        if needs_bounds_check:
            self._emit_line("// BASIS runtime bounds checking")
            self._emit_line("static void _basis_bounds_check(int32_t index, int32_t size) {")
            self._emit_line("    if (index < 0 || index >= size) {")
            self._emit_line('        fprintf(stderr, "BASIS RUNTIME ERROR: array index %d out of bounds (size %d)\\n", index, size);')
            self._emit_line("        exit(1);")
            self._emit_line("    }")
            self._emit_line("}")
            self._emit_line("")
        
        # Forward declarations for structs
        for decl in module.declarations:
            if isinstance(decl, StructDecl):
                self._emit_struct_forward(decl)
        
        if any(isinstance(d, StructDecl) for d in module.declarations):
            self._emit_line("")
        
        # Struct definitions
        for decl in module.declarations:
            if isinstance(decl, StructDecl):
                self._emit_struct(decl)
        
        # Function declarations (for forward references)
        for decl in module.declarations:
            if isinstance(decl, FunctionDecl):
                self._emit_function_declaration(decl)
        
        if any(isinstance(d, FunctionDecl) for d in module.declarations):
            self._emit_line("")
        
        # Constants
        for decl in module.declarations:
            if isinstance(decl, ConstDecl):
                self._emit_const(decl)
        
        # Function definitions
        for decl in module.declarations:
            if isinstance(decl, FunctionDecl) and decl.body:
                self._emit_function(decl)
        
        return "\n".join(self.output)
    
    # ========================================================================
    # Type Emission
    # ========================================================================
    
    
    def _emit_type(self, type_node: Type) -> str:
        """Convert BASIS type to C type string."""
        if isinstance(type_node, TypeName):
            # Map BASIS types to C types
            type_map = {
                'i8': 'int8_t',
                'i16': 'int16_t',
                'i32': 'int32_t',
                'i64': 'int64_t',
                'u8': 'uint8_t',
                'u16': 'uint16_t',
                'u32': 'uint32_t',
                'u64': 'uint64_t',
                'f32': 'float',
                'f64': 'double',
                'bool': 'bool',
                'void': 'void',
            }
            if type_node.name in type_map:
                return type_map[type_node.name]
            else:
                # User-defined type (struct)
                return type_node.name
        
        elif isinstance(type_node, PointerType):
            base = self._emit_type(type_node.base_type)
            return f"{base}*"
        
        elif isinstance(type_node, ArrayType):
            # Arrays in C
            element = self._emit_type(type_node.element_type)
            # Size will be added by caller
            return element
        
        elif isinstance(type_node, VolatileType):
            base = self._emit_type(type_node.base_type)
            return f"volatile {base}"
        
        return "void"
    
    # ========================================================================
    # Struct Emission
    # ========================================================================
    
    def _emit_struct_forward(self, decl: StructDecl):
        """Emit forward declaration for struct."""
        self._emit_line(f"typedef struct {decl.name} {decl.name};")
    
    def _emit_struct(self, decl: StructDecl):
        """Emit struct definition."""
        # Check for @align annotation
        align_val = self._get_annotation_arg(decl.annotations if hasattr(decl, 'annotations') else None, 'align', 'value')
        
        self._emit_line(f"struct {decl.name} {{")
        self.indent_level += 1
        
        for field in decl.fields:
            field_type = self._emit_type(field.type)
            if isinstance(field.type, ArrayType):
                # Array field - need size
                size_expr = self._emit_expression(field.type.size_expr)
                self._emit_line(f"{field_type} {field.name}[{size_expr}];")
            else:
                self._emit_line(f"{field_type} {field.name};")
        
        self.indent_level -= 1
        if align_val:
            self._emit_line(f"}} __attribute__((aligned({align_val})));")
        else:
            self._emit_line("};")
    
    # ========================================================================
    # Constant Emission
    # ========================================================================
    
    def _emit_const(self, decl: ConstDecl):
        """Emit constant definition."""
        c_type = self._emit_type(decl.type)
        value = self._emit_expression(decl.value)
        self._emit_line(f"static const {c_type} {decl.name} = {value};")
    
    # ========================================================================
    # Function Emission
    # ========================================================================
    
    def _has_annotation(self, annotations, name):
        """Check if a list of annotations contains one with the given name."""
        if not annotations:
            return False
        for ann in annotations:
            if ann.name == name:
                return True
        return False
    
    def _get_annotation_arg(self, annotations, ann_name, arg_name):
        """Get a named argument from an annotation."""
        if not annotations:
            return None
        for ann in annotations:
            if ann.name == ann_name and ann.arguments:
                return ann.arguments.get(arg_name)
        return None
    
    def _emit_function_declaration(self, decl: FunctionDecl):
        """Emit function declaration."""
        if decl.is_extern:
            return  # Skip extern declarations
        
        return_type = self._emit_type(decl.return_type)
        params = self._emit_params(decl.params)
        
        prefix = ""
        if self._has_annotation(decl.annotations, 'inline'):
            prefix = "static inline "
        if self._has_annotation(decl.annotations, 'interrupt'):
            prefix += "BASIS_INTERRUPT "
        
        self._emit_line(f"{prefix}{return_type} {decl.name}({params});")
    
    def _emit_function(self, decl: FunctionDecl):
        """Emit function definition."""
        return_type = self._emit_type(decl.return_type)
        params = self._emit_params(decl.params)
        
        prefix = ""
        if self._has_annotation(decl.annotations, 'inline'):
            prefix = "static inline "
        if self._has_annotation(decl.annotations, 'interrupt'):
            prefix += "BASIS_INTERRUPT "
        
        self._emit_line(f"{prefix}{return_type} {decl.name}({params}) {{")
        self.indent_level += 1
        
        if decl.body:
            self._emit_block_contents(decl.body)
        
        self.indent_level -= 1
        self._emit_line("}")
        self._emit_line("")
    
    def _emit_params(self, params: List[Param]) -> str:
        """Emit function parameters."""
        if not params:
            return "void"
        
        param_strs = []
        for param in params:
            param_type = self._emit_type(param.type)
            if isinstance(param.type, ArrayType):
                # Array parameter becomes pointer
                param_strs.append(f"{param_type}* {param.name}")
            else:
                param_strs.append(f"{param_type} {param.name}")
        
        return ", ".join(param_strs)
    
    # ========================================================================
    # Statement Emission
    # ========================================================================
    
    def _emit_block_contents(self, block: Block):
        """Emit statements in a block."""
        for stmt in block.statements:
            self._emit_statement(stmt)
    
    def _emit_statement(self, stmt: Statement):
        """Emit a statement."""
        if isinstance(stmt, Block):
            self._emit_line("{")
            self.indent_level += 1
            self._emit_block_contents(stmt)
            self.indent_level -= 1
            self._emit_line("}")
        
        elif isinstance(stmt, LetDecl):
            var_type = self._emit_type(stmt.type)
            if isinstance(stmt.type, ArrayType):
                size_expr = self._emit_expression(stmt.type.size_expr)
                if stmt.initializer:
                    init = self._emit_expression(stmt.initializer)
                    self._emit_line(f"{var_type} {stmt.name}[{size_expr}] = {init};")
                else:
                    self._emit_line(f"{var_type} {stmt.name}[{size_expr}];")
            else:
                if stmt.initializer:
                    init = self._emit_expression(stmt.initializer)
                    self._emit_line(f"{var_type} {stmt.name} = {init};")
                else:
                    self._emit_line(f"{var_type} {stmt.name};")
        
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                value = self._emit_expression(stmt.value)
                self._emit_line(f"return {value};")
            else:
                self._emit_line("return;")
        
        elif isinstance(stmt, IfStmt):
            condition = self._emit_expression(stmt.condition)
            self._emit_line(f"if ({condition}) {{")
            self.indent_level += 1
            self._emit_block_contents(stmt.then_block)
            self.indent_level -= 1
            
            for elif_branch in stmt.elif_branches:
                elif_cond = self._emit_expression(elif_branch.condition)
                self._emit_line(f"}} else if ({elif_cond}) {{")
                self.indent_level += 1
                self._emit_block_contents(elif_branch.block)
                self.indent_level -= 1
            
            if stmt.else_block:
                self._emit_line("} else {")
                self.indent_level += 1
                self._emit_block_contents(stmt.else_block)
                self.indent_level -= 1
            
            self._emit_line("}")
        
        elif isinstance(stmt, ForStmt):
            # BASIS: for i in start..end
            # C: for (i = start; i < end; i++)
            start = self._emit_expression(stmt.range_start)
            end = self._emit_expression(stmt.range_end)
            
            self._emit_line(f"for (int32_t {stmt.iterator_name} = {start}; {stmt.iterator_name} < {end}; {stmt.iterator_name}++) {{")
            self.indent_level += 1
            self._emit_block_contents(stmt.body)
            self.indent_level -= 1
            self._emit_line("}")
        
        elif isinstance(stmt, WhileStmt):
            cond = self._emit_expression(stmt.condition)
            self._emit_line(f"while ({cond}) {{")
            self.indent_level += 1
            self._emit_block_contents(stmt.body)
            self.indent_level -= 1
            self._emit_line("}")
        
        elif isinstance(stmt, BreakStmt):
            self._emit_line("break;")
        
        elif isinstance(stmt, ContinueStmt):
            self._emit_line("continue;")
        
        elif isinstance(stmt, ExprStmt):
            expr = self._emit_expression(stmt.expression)
            self._emit_line(f"{expr};")
    
    # ========================================================================
    # Expression Emission
    # ========================================================================
    
    def _emit_expression(self, expr: Expression) -> str:
        """Emit an expression."""
        if isinstance(expr, LiteralExpr):
            if expr.kind == 'string':
                # String literal - escape special characters for C
                escaped = expr.value
                # First escape backslashes, then other special chars
                escaped = escaped.replace('\\', '\\\\')
                escaped = escaped.replace('"', '\\"')
                escaped = escaped.replace('\n', '\\n')
                escaped = escaped.replace('\t', '\\t')
                escaped = escaped.replace('\r', '\\r')
                escaped = escaped.replace('\0', '\\0')
                return f'"{escaped}"'
            elif expr.kind == 'bool':
                return 'true' if expr.value.lower() == 'true' else 'false'
            else:
                return expr.value
        
        elif isinstance(expr, IdentifierExpr):
            return expr.name
        
        elif isinstance(expr, BinaryExpr):
            left = self._emit_expression(expr.left)
            right = self._emit_expression(expr.right)
            return f"({left} {expr.operator} {right})"
        
        elif isinstance(expr, UnaryExpr):
            operand = self._emit_expression(expr.operand)
            return f"({expr.operator}{operand})"
        
        elif isinstance(expr, CallExpr):
            callee = self._emit_expression(expr.callee)
            
            # Special case for alloc
            if isinstance(expr.callee, IdentifierExpr) and expr.callee.name == "alloc":
                # alloc(type, count) -> malloc(count * sizeof(type))
                if len(expr.arguments) >= 2:
                    type_arg = expr.arguments[0]
                    size = self._emit_expression(expr.arguments[1])
                    # Determine sizeof from the type argument
                    if isinstance(type_arg, IdentifierExpr):
                        type_name = type_arg.name
                        sizeof_map = {
                            'i8': 1, 'u8': 1, 'i16': 2, 'u16': 2,
                            'i32': 4, 'u32': 4, 'i64': 8, 'u64': 8,
                            'f32': 4, 'f64': 8, 'bool': 1,
                        }
                        if type_name in sizeof_map:
                            elem_size = sizeof_map[type_name]
                            return f"malloc({size} * {elem_size})"
                        else:
                            # Struct type — use sizeof
                            return f"malloc({size} * sizeof({type_name}))"
                    return f"malloc({size})"
                else:
                    return "malloc(0)"
            
            args = ", ".join(self._emit_expression(arg) for arg in expr.arguments)
            return f"{callee}({args})"
        
        elif isinstance(expr, IndexExpr):
            base = self._emit_expression(expr.base)
            index = self._emit_expression(expr.index)
            
            # Runtime bounds check for array access with known size
            if expr.array_size is not None:
                # Check if index is a compile-time constant (already checked at compile time)
                is_constant = isinstance(expr.index, LiteralExpr) and expr.index.kind == 'int'
                if not is_constant:
                    # Emit runtime bounds check
                    self._emit_line(f"_basis_bounds_check({index}, {expr.array_size});")
            
            return f"{base}[{index}]"
        
        elif isinstance(expr, FieldAccessExpr):
            base = self._emit_expression(expr.base)
            op = "->" if expr.base_is_pointer else "."
            return f"{base}{op}{expr.field_name}"
        
        elif isinstance(expr, AssignmentExpr):
            target = self._emit_expression(expr.target)
            value = self._emit_expression(expr.value)
            return f"{target} {expr.operator} {value}"
        
        elif isinstance(expr, AddressOfExpr):
            operand = self._emit_expression(expr.operand)
            return f"(&{operand})"
        
        elif isinstance(expr, DereferenceExpr):
            operand = self._emit_expression(expr.operand)
            return f"(*{operand})"
        
        elif isinstance(expr, CastExpr):
            value = self._emit_expression(expr.expression)
            target_type = self._emit_type(expr.target_type)
            return f"(({target_type})({value}))"
        
        elif isinstance(expr, ArrayLiteralExpr):
            # Array literal: {elem1, elem2, ...}
            elements = ", ".join(self._emit_expression(elem) for elem in expr.elements)
            return f"{{{elements}}}"
        
        elif isinstance(expr, ArrayRepeatExpr):
            # Array repeat: [value; count] -> {value, value, value, ...}
            # or with overrides: [value; count | idx: val, ...] -> {value, ..., val@idx, ...}
            count = self._eval_const_int(expr.count)
            default_val = self._emit_expression(expr.value)
            
            if expr.overrides:
                # Build array with overrides
                elements = [default_val] * count
                for override in expr.overrides:
                    idx = self._eval_const_int(override.index)
                    if 0 <= idx < count:
                        elements[idx] = self._emit_expression(override.value)
                return "{" + ", ".join(elements) + "}"
            else:
                # Simple repeat
                elements = ", ".join([default_val] * count)
                return f"{{{elements}}}"
        
        elif isinstance(expr, StructLiteralExpr):
            # Struct literal: (StructName){.field1 = value1, .field2 = value2, ...}
            field_inits = ", ".join(
                f".{field.field_name} = {self._emit_expression(field.value)}"
                for field in expr.field_inits
            )
            return f"({expr.struct_name}){{{field_inits}}}"
        
        return "/* unknown expr */"
    
    def _eval_const_int(self, expr: Expression) -> int:
        """Evaluate a constant integer expression. Used for array repeat count."""
        if isinstance(expr, LiteralExpr) and expr.kind == 'int':
            return parse_int_literal(expr.value)
        # For casts like (5 as u32), extract inner value
        if isinstance(expr, CastExpr):
            return self._eval_const_int(expr.expression)
        return 0  # Fallback (should be caught by typecheck)
    
    # ========================================================================
    # AST Scanning (for conditional runtime helper emission)
    # ========================================================================
    
    def _collect_used_helpers(self, module: Module) -> set:
        """Scan AST to find which runtime helpers are actually referenced."""
        used = set()
        all_helpers = set(self.RUNTIME_HELPERS.keys())
        
        def scan_expr(expr):
            if expr is None:
                return
            if isinstance(expr, CallExpr):
                if isinstance(expr.callee, IdentifierExpr):
                    name = expr.callee.name
                    if name in all_helpers:
                        used.add(name)
                        for dep in self.HELPER_DEPS.get(name, ()):
                            used.add(dep)
                for arg in expr.arguments:
                    scan_expr(arg)
            elif isinstance(expr, BinaryExpr):
                scan_expr(expr.left)
                scan_expr(expr.right)
            elif isinstance(expr, UnaryExpr):
                scan_expr(expr.operand)
            elif isinstance(expr, CastExpr):
                scan_expr(expr.expression)
            elif isinstance(expr, IndexExpr):
                scan_expr(expr.base)
                scan_expr(expr.index)
            elif isinstance(expr, FieldAccessExpr):
                scan_expr(expr.base)
            elif isinstance(expr, AssignmentExpr):
                scan_expr(expr.target)
                scan_expr(expr.value)
            elif isinstance(expr, AddressOfExpr):
                scan_expr(expr.operand)
            elif isinstance(expr, DereferenceExpr):
                scan_expr(expr.operand)
            elif isinstance(expr, ArrayLiteralExpr):
                for elem in expr.elements:
                    scan_expr(elem)
            elif isinstance(expr, ArrayRepeatExpr):
                scan_expr(expr.value)
                scan_expr(expr.count)
            elif isinstance(expr, StructLiteralExpr):
                for fi in expr.field_inits:
                    scan_expr(fi.value)
        
        def scan_stmt(stmt):
            if isinstance(stmt, LetDecl):
                if stmt.initializer:
                    scan_expr(stmt.initializer)
            elif isinstance(stmt, ExprStmt):
                scan_expr(stmt.expression)
            elif isinstance(stmt, ReturnStmt):
                if stmt.value:
                    scan_expr(stmt.value)
            elif isinstance(stmt, IfStmt):
                scan_expr(stmt.condition)
                scan_block(stmt.then_block)
                for branch in stmt.elif_branches:
                    scan_expr(branch.condition)
                    scan_block(branch.block)
                if stmt.else_block:
                    scan_block(stmt.else_block)
            elif isinstance(stmt, ForStmt):
                scan_expr(stmt.range_start)
                scan_expr(stmt.range_end)
                scan_block(stmt.body)
            elif isinstance(stmt, WhileStmt):
                scan_expr(stmt.condition)
                scan_block(stmt.body)
        
        def scan_block(block):
            if block:
                for stmt in block.statements:
                    scan_stmt(stmt)
        
        for decl in module.declarations:
            if isinstance(decl, FunctionDecl) and decl.body:
                scan_block(decl.body)
        
        return used
    
    def _needs_bounds_check(self, module: Module) -> bool:
        """Check if any array index uses a non-constant index (needs runtime check)."""
        def scan_expr(expr):
            if expr is None:
                return False
            if isinstance(expr, IndexExpr):
                if expr.array_size is not None:
                    if not (isinstance(expr.index, LiteralExpr) and expr.index.kind == 'int'):
                        return True
                return scan_expr(expr.base) or scan_expr(expr.index)
            elif isinstance(expr, BinaryExpr):
                return scan_expr(expr.left) or scan_expr(expr.right)
            elif isinstance(expr, UnaryExpr):
                return scan_expr(expr.operand)
            elif isinstance(expr, CallExpr):
                return any(scan_expr(a) for a in expr.arguments)
            elif isinstance(expr, CastExpr):
                return scan_expr(expr.expression)
            elif isinstance(expr, AssignmentExpr):
                return scan_expr(expr.target) or scan_expr(expr.value)
            elif isinstance(expr, FieldAccessExpr):
                return scan_expr(expr.base)
            elif isinstance(expr, AddressOfExpr):
                return scan_expr(expr.operand)
            elif isinstance(expr, DereferenceExpr):
                return scan_expr(expr.operand)
            return False
        
        def scan_stmt(stmt):
            if isinstance(stmt, LetDecl):
                return stmt.initializer and scan_expr(stmt.initializer)
            elif isinstance(stmt, ExprStmt):
                return scan_expr(stmt.expression)
            elif isinstance(stmt, ReturnStmt):
                return stmt.value and scan_expr(stmt.value)
            elif isinstance(stmt, IfStmt):
                if scan_expr(stmt.condition) or scan_block(stmt.then_block):
                    return True
                for branch in stmt.elif_branches:
                    if scan_expr(branch.condition) or scan_block(branch.block):
                        return True
                return stmt.else_block and scan_block(stmt.else_block)
            elif isinstance(stmt, ForStmt):
                return scan_block(stmt.body)
            elif isinstance(stmt, WhileStmt):
                return scan_expr(stmt.condition) or scan_block(stmt.body)
            return False
        
        def scan_block(block):
            return block and any(scan_stmt(s) for s in block.statements)
        
        for decl in module.declarations:
            if isinstance(decl, FunctionDecl) and decl.body:
                if scan_block(decl.body):
                    return True
        return False
    
    # ========================================================================
    # Output Helpers
    # ========================================================================
    
    def _emit_line(self, line: str):
        """Emit a line with current indentation."""
        if line:
            indent = "    " * self.indent_level
            self.output.append(f"{indent}{line}")
        else:
            self.output.append("")


# ============================================================================
# Convenience Function
# ============================================================================

def generate_c_code(module: Module) -> str:
    """
    Generate C code for a BASIS module.
    Returns the C code as a string.
    """
    generator = CCodeGenerator()
    return generator.generate(module)
