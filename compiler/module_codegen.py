"""
BASIS Multi-Module Code Generator
Generates .h and .c files for each module with proper dependency handling.
"""

from typing import Dict, List, Set, Optional
from pathlib import Path
from ast_defs import *
from codegen import CCodeGenerator
from diagnostics import DiagnosticEngine


class ModuleCodeGenerator:
    """
    Generates C code for multiple BASIS modules with headers.
    """
    
    def __init__(self, diag_engine: DiagnosticEngine, export_all: bool = False):
        self.diag = diag_engine
        self.modules: Dict[str, Module] = {}
        self.import_graph: Dict[str, Set[str]] = {}
        self.export_all = export_all  # For library mode: export all functions
    
    def add_module(self, module: Module):
        """Add a module to the compilation unit."""
        self.modules[module.name] = module
        
        # Build import graph
        imports = set()
        for decl in module.declarations:
            if isinstance(decl, ImportDecl):
                imports.add(decl.module_name)
        self.import_graph[module.name] = imports
    
    def check_import_cycles(self) -> bool:
        """Check for import cycles. Returns True if no cycles found."""
        def visit(node: str, path: List[str]) -> bool:
            if node in path:
                cycle = path + [node]
                self.diag.error(
                    'E_CYCLIC_IMPORT',
                    f"cyclic import detected: {' -> '.join(cycle)}",
                    1, 1
                )
                return False
            
            new_path = path + [node]
            for dep in self.import_graph.get(node, set()):
                if not visit(dep, new_path):
                    return False
            
            return True
        
        for module_name in self.modules:
            if not visit(module_name, []):
                return False
        
        return True
    
    def validate_imports(self) -> bool:
        """Validate that all imported modules exist."""
        valid = True
        for module_name, imports in self.import_graph.items():
            for imported in imports:
                if imported not in self.modules:
                    self.diag.error(
                        'E_UNKNOWN_MODULE',
                        f"module '{module_name}' imports unknown module '{imported}'",
                        1, 1
                    )
                    valid = False
        return valid
    
    def generate_all(self, output_dir: Path) -> bool:
        """Generate .h and .c files for all modules."""
        if not self.validate_imports():
            return False
        
        if not self.check_import_cycles():
            return False
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for module_name, module in self.modules.items():
            # Generate header only for non-entry modules (skip main.h)
            if module_name != 'main':
                header_path = output_dir / f"{module_name}.h"
                header_code = self._generate_header(module)
                header_path.write_text(header_code)
            
            # Generate implementation
            impl_path = output_dir / f"{module_name}.c"
            impl_code = self._generate_implementation(module)
            impl_path.write_text(impl_code)
        
        return True
    
    def _generate_header(self, module: Module) -> str:
        """Generate header file for a module."""
        lines = []
        
        # Header guard
        guard = f"{module.name.upper()}_H"
        lines.append(f"#ifndef {guard}")
        lines.append(f"#define {guard}")
        lines.append("")
        lines.append("#include <stdint.h>")
        lines.append("#include <stdbool.h>")
        lines.append("")
        
        # Extract public declarations only
        has_content = False
        
        # Public structs
        for decl in module.declarations:
            if isinstance(decl, StructDecl) and (decl.visibility == 'public' or self.export_all):
                has_content = True
                lines.append(self._emit_struct_decl(decl))
                lines.append("")
        
        # Function declarations (public or all if export_all mode)
        for decl in module.declarations:
            if isinstance(decl, FunctionDecl) and not decl.is_extern:
                should_export = decl.visibility == 'public' or self.export_all
                if should_export:
                    has_content = True
                    lines.append(self._emit_function_decl(decl))
        
        # Constants (public or all if export_all mode)
        for decl in module.declarations:
            if isinstance(decl, ConstDecl):
                should_export = decl.visibility == 'public' or self.export_all
                if should_export:
                    has_content = True
                    gen = CCodeGenerator()
                    c_type = gen._emit_type(decl.type)
                    lines.append(f"extern const {c_type} {decl.name};")
        
        lines.append("")
        lines.append(f"#endif /* {guard} */")
        
        return "\n".join(lines)
    
    def _generate_implementation(self, module: Module) -> str:
        """Generate implementation (.c) file for a module."""
        lines = []
        
        # Include own header (skip for entry module)
        if module.name != 'main':
            lines.append(f'#include "{module.name}.h"')
        lines.append("#include <stdint.h>")
        lines.append("#include <stdbool.h>")
        lines.append("#include <stdlib.h>")
        lines.append("#include <stdio.h>")
        lines.append("#include <string.h>")
        lines.append("")
        
        # Scan AST and emit only the runtime helpers this module actually uses
        gen_scan = CCodeGenerator()
        used_helpers = gen_scan._collect_used_helpers(module)
        needs_bounds = gen_scan._needs_bounds_check(module)
        
        if used_helpers:
            lines.append("// BASIS runtime helpers")
            for name in CCodeGenerator.RUNTIME_HELPERS:
                if name in used_helpers:
                    lines.append(CCodeGenerator.RUNTIME_HELPERS[name])
            lines.append("")
        
        if needs_bounds:
            lines.append("// BASIS runtime bounds checking")
            lines.append("static void _basis_bounds_check(int32_t index, int32_t size) {")
            lines.append("    if (index < 0 || index >= size) {")
            lines.append('        fprintf(stderr, "BASIS RUNTIME ERROR: array index %d out of bounds (size %d)\\n", index, size);')
            lines.append("        exit(1);")
            lines.append("    }")
            lines.append("}")
            lines.append("")
        
        # Include headers for imported modules
        
        # Include headers for imported modules
        imports = self.import_graph.get(module.name, set())
        for imported in sorted(imports):
            lines.append(f'#include "{imported}.h"')
        if imports:
            lines.append("")
        
        # Use existing CCodeGenerator for the body
        gen = CCodeGenerator()
        gen.output = []
        
        # Emit private structs
        for decl in module.declarations:
            if isinstance(decl, StructDecl) and decl.visibility != 'public':
                gen._emit_struct_forward(decl)
        
        for decl in module.declarations:
            if isinstance(decl, StructDecl) and decl.visibility != 'public':
                gen._emit_struct(decl)
        
        # Emit all constants (public ones as definitions, private as static)
        for decl in module.declarations:
            if isinstance(decl, ConstDecl):
                c_type = gen._emit_type(decl.type)
                value = gen._emit_expression(decl.value)
                if decl.visibility == 'public' or self.export_all:
                    gen._emit_line(f"const {c_type} {decl.name} = {value};")
                else:
                    gen._emit_line(f"static const {c_type} {decl.name} = {value};")
        
        if any(isinstance(d, ConstDecl) for d in module.declarations):
            gen._emit_line("")
        
        # Forward declarations for all functions (for mutual recursion)
        for decl in module.declarations:
            if isinstance(decl, FunctionDecl) and not decl.is_extern:
                # Skip forward declaration for main
                if decl.name == 'main':
                    continue
                return_type = gen._emit_type(decl.return_type)
                params = gen._emit_params(decl.params)
                # Use static only if not public and not in export_all mode
                if decl.visibility != 'public' and not self.export_all:
                    gen._emit_line(f"static {return_type} {decl.name}({params});")
                # Public/exported functions already declared in header
        
        if any(isinstance(d, FunctionDecl) and not d.is_extern for d in module.declarations):
            gen._emit_line("")
        
        # Emit all function definitions
        for decl in module.declarations:
            if isinstance(decl, FunctionDecl) and decl.body and not decl.is_extern:
                self._emit_function_impl(gen, decl)
        
        lines.extend(gen.output)
        
        return "\n".join(lines)
    
    def _emit_struct_decl(self, decl: StructDecl) -> str:
        """Emit struct declaration for header."""
        lines = [f"typedef struct {decl.name} {decl.name};"]
        lines.append(f"struct {decl.name} {{")
        
        gen = CCodeGenerator()
        for field in decl.fields:
            field_type = gen._emit_type(field.type)
            if isinstance(field.type, ArrayType):
                size_expr = gen._emit_expression(field.type.size_expr)
                lines.append(f"    {field_type} {field.name}[{size_expr}];")
            else:
                lines.append(f"    {field_type} {field.name};")
        
        lines.append("};")
        return "\n".join(lines)
    
    def _emit_function_decl(self, decl: FunctionDecl) -> str:
        """Emit function declaration for header."""
        gen = CCodeGenerator()
        return_type = gen._emit_type(decl.return_type)
        params = gen._emit_params(decl.params)
        return f"{return_type} {decl.name}({params});"
    
    def _emit_function_impl(self, gen: CCodeGenerator, decl: FunctionDecl):
        """Emit function implementation using existing generator."""
        return_type = gen._emit_type(decl.return_type)
        params = gen._emit_params(decl.params)
        
        # Add static for private functions (but never for main or in export_all mode)
        is_private = decl.visibility != 'public' and not self.export_all
        if is_private and decl.name != 'main':
            gen._emit_line(f"static {return_type} {decl.name}({params}) {{")
        else:
            gen._emit_line(f"{return_type} {decl.name}({params}) {{")
        
        gen.indent_level += 1
        
        if decl.body:
            gen._emit_block_contents(decl.body)
        
        gen.indent_level -= 1
        gen._emit_line("}")
        gen._emit_line("")