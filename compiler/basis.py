"""
BASIS Compiler Driver
Single entry-point CLI tool for the BASIS compiler.
"""

import sys
import os
import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict

# Import all compiler stages
from lexer import Lexer
from parser import Parser
from diagnostics import DiagnosticEngine
from sema import SemanticAnalyzer, ModuleRegistry
from typecheck import TypeChecker, check_types
from consteval import evaluate_constants
from loop_analysis import analyze_loops
from resource_analysis import analyze_program_resources
from module_codegen import ModuleCodeGenerator
from ast_defs import Module, FunctionDecl, ImportDecl
from target_config import TargetConfig, PREDEFINED_TARGETS


def to_native_tool_path(pathlike) -> str:
    r"""
    Normalize paths passed to external Windows tools.

    Python can surface extended-length paths such as ``\\?\D:\...`` on Windows.
    Some toolchains (including common MinGW gcc builds) do not accept that form,
    so strip the prefix before invoking external processes.
    """
    path = os.path.normpath(os.fspath(pathlike))
    if os.name == "nt":
        if path.startswith("\\\\?\\UNC\\"):
            return "\\" + path[7:]
        if path.startswith("\\\\?\\"):
            return path[4:]
    return path


@dataclass
class CodeSizeInfo:
    display_bytes: int
    exact_bytes: Optional[int]
    summary_label: str
    note: Optional[str] = None


def estimate_code_size_bytes(modules: Dict[str, Module]) -> int:
    """Fallback heuristic used only when no linked artifact is available."""
    total_functions = sum(
        len([decl for decl in module.declarations if isinstance(decl, FunctionDecl)])
        for module in modules.values()
    )
    return total_functions * 100


def parse_size_total(size_output: str) -> Optional[int]:
    """Extract the total byte count from `size -A` output."""
    for line in reversed(size_output.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("Total"):
            continue
        parts = stripped.split()
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
    return None


def compile_objects(c_files: List[Path], output_path: Path) -> List[Path]:
    """Compile generated C files to object files for size measurement and linking."""
    object_files: List[Path] = []
    for c_file in c_files:
        object_path = output_path / f"{c_file.stem}.o"
        compile_cmd = [
            "gcc",
            "-std=c99",
            "-c",
            to_native_tool_path(c_file),
            "-o",
            to_native_tool_path(object_path),
        ]
        result = subprocess.run(compile_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(details or f"failed to compile {c_file.name} to object code")
        object_files.append(object_path)
    return object_files


def measure_object_code_size(object_files: List[Path]) -> int:
    """Measure compiled code size using object section totals."""
    total_bytes = 0
    for object_file in object_files:
        size_cmd = ["size", "-A", to_native_tool_path(object_file)]
        result = subprocess.run(size_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(details or f"failed to inspect {object_file.name}")
        measured = parse_size_total(result.stdout)
        if measured is None:
            raise RuntimeError(f"unable to parse code size for {object_file.name}")
        total_bytes += measured
    return total_bytes


def build_code_size_info(
    estimated_code_size: int,
    exact_code_size: Optional[int],
    *,
    emit_c_only: bool,
    is_library: bool,
    fallback_reason: Optional[str] = None,
) -> CodeSizeInfo:
    """Describe how code size should be reported and whether it is enforceable."""
    if exact_code_size is not None:
        return CodeSizeInfo(
            display_bytes=exact_code_size,
            exact_bytes=exact_code_size,
            summary_label="Code",
        )

    if emit_c_only:
        note = (
            "Code size is estimated only because --emit-c skips binary generation; "
            "code bytes are not enforced in #[max_memory] or flash budgets."
        )
    elif is_library:
        note = (
            "Code size is estimated only for --lib builds; "
            "code bytes are not enforced in #[max_memory] or flash budgets."
        )
    else:
        note = (
            "Code size could not be measured; falling back to an estimate for reporting only."
        )

    if fallback_reason:
        note = f"{note} Reason: {fallback_reason}"

    return CodeSizeInfo(
        display_bytes=estimated_code_size,
        exact_bytes=None,
        summary_label="Code (~)",
        note=note,
    )


def validate_main_function(modules: Dict[str, Module], is_library_build: bool = False) -> Optional[str]:
    """
    Validate main() function requirements.
    
    For library builds: main() is optional (allows building library modules)
    For executable builds: exactly one main() must exist
    
    Returns error message if validation fails, None otherwise.
    """
    main_funcs = []
    
    for module_name, module in modules.items():
        for decl in module.declarations:
            if isinstance(decl, FunctionDecl) and decl.name == 'main':
                main_funcs.append((module_name, decl))
    
    # For library builds, main() is optional
    if is_library_build:
        if len(main_funcs) > 1:
            modules_with_main = [name for name, _ in main_funcs]
            return f"multiple main() functions found in: {', '.join(modules_with_main)}"
        # 0 or 1 main() is fine for libraries
        if len(main_funcs) == 0:
            return None  # No main() is valid for libraries
    else:
        # For executable builds, require exactly one main()
        if len(main_funcs) == 0:
            return "no main() function found (use --lib to build library modules)"
        
        if len(main_funcs) > 1:
            modules_with_main = [name for name, _ in main_funcs]
            return f"multiple main() functions found in: {', '.join(modules_with_main)}"
    
    # If we have a main(), validate its signature
    if len(main_funcs) == 1:
        module_name, main_func = main_funcs[0]
        
        # main() must not be private (if present, it's the entry point or test harness)
        if main_func.visibility == 'private':
            return "main() cannot be private"
    
    return None


def compile_basis(input_files: List[str], 
                  output_dir: str,
                  emit_c_only: bool,
                  run_after: bool,
                  target_config: Optional[TargetConfig] = None,
                  show_resources: bool = False,
                  is_library: bool = False,
                  stdlib_path: Optional[str] = None) -> int:
    """
    Main compilation pipeline.
    Returns exit code (0 = success, non-zero = failure).
    """
    print(f"[COMPILE] Starting compilation of {input_files}")
    
    # Initialize diagnostics
    diag = DiagnosticEngine()
    
    # Convert input files to absolute paths and validate
    source_files = []
    source_dirs = set()  # Track directories to search for imports
    
    for file_path in input_files:
        abs_path = Path(file_path).resolve()
        if not abs_path.exists():
            print(f"error: file not found: {file_path}", file=sys.stderr)
            return 1
        if abs_path.suffix != '.bs':
            print(f"error: not a BASIS file: {file_path}", file=sys.stderr)
            return 1
        source_files.append(abs_path)
        source_dirs.add(abs_path.parent)
    
    # Add standard library path to search directories
    stdlib_modules = set()  # Track which modules are from stdlib
    stdlib_dirs = set()  # Track stdlib directories
    
    if stdlib_path:
        stdlib_dir = Path(stdlib_path).resolve()
        if stdlib_dir.exists() and stdlib_dir.is_dir():
            source_dirs.add(stdlib_dir)
            stdlib_dirs.add(stdlib_dir)
    else:
        # Determine base directory (handle both script and PyInstaller exe)
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller exe - look for stdlib relative to exe
            exe_dir = Path(sys.executable).parent
            # Try: exe_dir/../stdlib (exe is in bin/)
            possible_paths = [
                exe_dir.parent / "stdlib",  # bin/../stdlib
                exe_dir / "stdlib",          # same dir as exe
            ]
        else:
            # Running as script - look relative to compiler dir
            compiler_dir = Path(__file__).parent
            project_root = compiler_dir.parent
            possible_paths = [project_root / "stdlib"]
        
        for default_stdlib in possible_paths:
            if default_stdlib.exists() and default_stdlib.is_dir():
                # Add all subdirectories in stdlib as search paths, skipping build outputs
                for subdir in default_stdlib.iterdir():
                    if subdir.is_dir() and subdir.name != "build":
                        source_dirs.add(subdir)
                        stdlib_dirs.add(subdir)
                break
    
    # Create output directory (clean stale build artifacts to avoid linking old files)
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    for stale in list(output_path.glob("*.c")) + list(output_path.glob("*.h")) + list(output_path.glob("*.o")):
        stale.unlink()
    
    # Module registry for imports
    registry = ModuleRegistry()
    
    # Storage for pipeline stages
    modules = {}
    module_scopes = {}
    processed_modules = set()  # Track which modules we've already processed
    
    # Helper function to find and load a module
    def load_module(module_name: str) -> bool:
        """Load a module by name, searching in source directories."""
        if module_name in processed_modules:
            return True  # Already loaded
        
        # Search for module file in source directories
        for search_dir in source_dirs:
            module_file = search_dir / f"{module_name}.bs"
            if module_file.exists():
                # Track if this is a stdlib module
                if search_dir in stdlib_dirs:
                    stdlib_modules.add(module_name)
                
                # Read source
                try:
                    source_code = module_file.read_text(encoding='utf-8')
                except Exception as e:
                    print(f"error: cannot read file {module_file}: {e}", file=sys.stderr)
                    return False
                
                # Lexing
                lexer = Lexer(source_code, filename=str(module_file), diag_engine=diag)
                tokens = lexer.tokenize()
                
                if diag.has_errors():
                    return False
                
                # Parsing
                parser = Parser(tokens, filename=str(module_file), diag_engine=diag)
                parsed_module = parser.parse(module_name)
                
                if diag.has_errors() or parsed_module is None:
                    return False
                
                modules[module_name] = parsed_module
                processed_modules.add(module_name)
                registry.register_known_module(module_name)
                
                # Recursively load any imports in this module
                for decl in parsed_module.declarations:
                    if isinstance(decl, ImportDecl):
                        if not load_module(decl.module_name):
                            return False
                
                return True
        
        # Module not found
        print(f"error: module '{module_name}' not found in search paths", file=sys.stderr)
        return False
    
    # ========================================================================
    # STAGE 1 & 2: Lexing and Parsing with Auto-Discovery
    # ========================================================================
    
    for source_file in source_files:
        module_name = source_file.stem
        
        if module_name in processed_modules:
            continue  # Skip if already loaded as a dependency
        
        try:
            source_code = source_file.read_text(encoding='utf-8')
        except Exception as e:
            print(f"error: cannot read file {source_file}: {e}", file=sys.stderr)
            return 1
        
        lexer = Lexer(source_code, filename=str(source_file), diag_engine=diag)
        tokens = lexer.tokenize()
        
        if diag.has_errors():
            diag.print_all()
            return 1
        
        parser = Parser(tokens, filename=str(source_file), diag_engine=diag)
        module = parser.parse(module_name)
        
        if diag.has_errors():
            diag.print_all()
            return 1
        
        if module is None:
            print(f"error: failed to parse {source_file}", file=sys.stderr)
            return 1
        
        modules[module_name] = module
        processed_modules.add(module_name)
        registry.register_known_module(module_name)
        
        # Auto-discover and load imported modules
        for decl in module.declarations:
            if isinstance(decl, ImportDecl):
                if not load_module(decl.module_name):
                    diag.print_all()
                    return 1
    
    # ========================================================================
    # STAGE 3: Semantic Analysis (process dependencies first)
    # ========================================================================
    
    # Build dependency graph to determine processing order
    dependency_graph = {}
    for module_name, module in modules.items():
        deps = set()
        for decl in module.declarations:
            if isinstance(decl, ImportDecl):
                deps.add(decl.module_name)
        dependency_graph[module_name] = deps
    
    # Topological sort to process modules in dependency order
    processed = set()
    processing_order = []
    
    def visit(mod_name: str, visiting: set):
        # Skip if module doesn't exist (shouldn't happen due to load_module checks)
        if mod_name not in modules:
            return
            
        if mod_name in processed:
            return
            
        if mod_name in visiting:
            print(f"error: circular dependency detected involving module '{mod_name}'", file=sys.stderr)
            return
        
        visiting.add(mod_name)
        for dep in dependency_graph.get(mod_name, set()):
            visit(dep, visiting)
        visiting.remove(mod_name)
        
        processed.add(mod_name)
        processing_order.append(mod_name)
    
    for module_name in modules.keys():
        visit(module_name, set())
    
    # Process modules in dependency order
    for module_name in processing_order:
        module = modules[module_name]
        analyzer = SemanticAnalyzer(diag, registry)
        success = analyzer.analyze(module)
        
        if not success or diag.has_errors():
            diag.print_all()
            return 1
        
        if analyzer.module_scope is None:
            print(f"error: semantic analysis failed for {module_name}", file=sys.stderr)
            return 1
        
        module_scopes[module_name] = analyzer.module_scope
        
        # Register module exports for other modules to import
        registry.register_module(module_name, analyzer.module_scope.symbols)
    
    # ========================================================================
    # STAGE 4: Type Checking
    # ========================================================================
    
    type_checkers = {}
    
    for module_name, module in modules.items():
        scope = module_scopes[module_name]
        
        type_checker = TypeChecker(diag, scope)
        success = type_checker.check(module)
        
        if not success or diag.has_errors():
            diag.print_all()
            return 1
        
        type_checkers[module_name] = type_checker
    
    # ========================================================================
    # STAGE 5: Constant Evaluation
    # ========================================================================
    
    const_evaluators = {}
    
    for module_name, module in modules.items():
        type_checker = type_checkers[module_name]
        const_eval = evaluate_constants(module, diag, type_checker)
        
        if diag.has_errors():
            diag.print_all()
            return 1
        
        const_evaluators[module_name] = const_eval
    
    # ========================================================================
    # STAGE 6: Loop Analysis
    # ========================================================================
    
    loop_analyzers = {}
    
    for module_name, module in modules.items():
        scope = module_scopes[module_name]
        const_eval = const_evaluators[module_name]
        
        loop_analyzer = analyze_loops(module, diag, const_eval, scope)
        
        if diag.has_errors():
            diag.print_all()
            return 1
        
        loop_analyzers[module_name] = loop_analyzer
    
    # ========================================================================
    # STAGE 7: Resource Analysis
    # ========================================================================
    
    program_resources = analyze_program_resources(
        modules,
        diag,
        module_scopes,
        type_checkers,
        const_evaluators,
        loop_analyzers,
    )
    
    if diag.has_errors():
        diag.print_all()
        return 1
    
    # ========================================================================
    # Calculate resource usage that does not depend on linked artifacts
    # ========================================================================
    
    entry_function_names = []
    for module_name, module in modules.items():
        for decl in module.declarations:
            if not isinstance(decl, FunctionDecl):
                continue
            is_interrupt = any(annotation.name == "interrupt" for annotation in decl.annotations)
            if is_interrupt:
                entry_function_names.append(f"{module_name}::{decl.name}")
            elif not is_library and decl.name == "main":
                entry_function_names.append(f"{module_name}::{decl.name}")
            elif is_library and decl.visibility == "public":
                entry_function_names.append(f"{module_name}::{decl.name}")

    if not entry_function_names:
        entry_function_names = list(program_resources.get_all_resources().keys())

    total_stack = 0
    total_heap = 0
    total_storage_bytes = 0
    total_storage_objects = 0
    total_task_stack = 0
    deepest_path = []
    all_resources = program_resources.get_all_resources()
    for qualified_name in entry_function_names:
        resource = all_resources.get(qualified_name)
        if not resource:
            continue
        if resource.stack_bytes > total_stack:
            total_stack = resource.stack_bytes
            deepest_path = list(resource.call_path)
        total_heap += resource.heap_bytes
        total_storage_bytes += resource.storage_bytes
        total_storage_objects += resource.storage_objects
    total_task_stack = sum(resource.task_stack_bytes for resource in all_resources.values())
    runtime_memory_size = total_stack + total_heap + total_task_stack
    estimated_code_size = estimate_code_size_bytes(modules)
    
    # ========================================================================
    # Validate max_memory directive (required for ALL files)
    # BASIS is designed for linking with C code - every file must declare its budget
    # ========================================================================
    
    # Check that EVERY user module has max_memory declared (stdlib is exempt)
    modules_missing_directive = []
    for module_name, module in modules.items():
        # Skip stdlib modules - they don't need max_memory
        if module_name in stdlib_modules:
            continue
        if module.max_memory_bytes is None:
            modules_missing_directive.append(module_name)
    
    if modules_missing_directive:
        print(f"\nerror: missing #[max_memory(SIZE)] directive in module(s):", file=sys.stderr)
        for mod_name in modules_missing_directive:
            print(f"  - {mod_name}", file=sys.stderr)
        print(f"\nBASIS requires explicit memory budget declaration in EVERY file.", file=sys.stderr)
        print(f"This allows BASIS modules to be linked with C code for scheduling/control.", file=sys.stderr)
        print(f"Add at the top of each file: #[max_memory(SIZE)]  // e.g. #[max_memory(4kb)]", file=sys.stderr)
        return 1
    
    # Find module with main() function (if any) for budget validation
    main_module_name = None
    max_memory_declared = None
    
    for module_name, module in modules.items():
        for decl in module.declarations:
            if isinstance(decl, FunctionDecl) and decl.name == 'main':
                main_module_name = module_name
                max_memory_declared = module.max_memory_bytes
                break
        if main_module_name:
            break
    
    # For programs with main(), validate total against declared budget
    # For library builds (--lib), sum all max_memory declarations
    if is_library:
        # Sum all max_memory from user modules for library builds
        max_memory_declared = sum(
            module.max_memory_bytes for name, module in modules.items()
            if name not in stdlib_modules and module.max_memory_bytes
        )
    
    # ========================================================================
    # Validate main() function
    # ========================================================================
    
    main_error = validate_main_function(modules, is_library_build=is_library)
    if main_error:
        print(f"error: {main_error}", file=sys.stderr)
        return 1
    
    # ========================================================================
    # STAGE 8: Code Generation
    # ========================================================================
    
    # In library mode, export all functions for C linkage
    codegen = ModuleCodeGenerator(diag, export_all=is_library)
    for module in modules.values():
        codegen.add_module(module)
    
    success = codegen.generate_all(output_path)
    
    if not success or diag.has_errors():
        diag.print_all()
        return 1
    
    print(f"Generated C code in {to_native_tool_path(output_path)}")
    
    c_files = sorted(output_path.glob("*.c"))
    if not c_files:
        print("error: no C files generated", file=sys.stderr)
        return 1

    object_files: List[Path] = []
    exact_code_size = None
    code_size_fallback_reason = None
    allow_measurement_fallback = emit_c_only or is_library

    try:
        object_files = compile_objects(c_files, output_path)
        exact_code_size = measure_object_code_size(object_files)
    except FileNotFoundError as exc:
        if allow_measurement_fallback:
            code_size_fallback_reason = str(exc)
        else:
            print("error: gcc/binutils not found. Please install gcc and ensure gcc and size are in PATH.",
                  file=sys.stderr)
            return 1
    except RuntimeError as exc:
        if allow_measurement_fallback:
            code_size_fallback_reason = str(exc)
        else:
            print("error: object compilation failed", file=sys.stderr)
            print(str(exc), file=sys.stderr)
            return 1

    binary_path: Optional[Path] = None
    if not emit_c_only and not is_library:
        # ====================================================================
        # GCC Linking
        # ====================================================================
        
        # Determine binary name
        binary_name = "app.exe" if sys.platform == "win32" else "app"
        binary_path = output_path / binary_name
        
        # Build gcc command
        gcc_cmd = ["gcc", "-std=c99", "-o", to_native_tool_path(binary_path)]
        gcc_cmd.extend(to_native_tool_path(f) for f in object_files)
        
        print(f"Compiling with gcc...")
        
        try:
            result = subprocess.run(gcc_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print("error: gcc compilation failed", file=sys.stderr)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)
                if result.stdout:
                    print(result.stdout, file=sys.stderr)
                return 1
        except FileNotFoundError:
            print("error: gcc not found. Please install gcc and ensure it's in PATH.", 
                  file=sys.stderr)
            return 1
        except Exception as e:
            print(f"error: failed to invoke gcc: {e}", file=sys.stderr)
            return 1
        
        print(f"Built executable: {to_native_tool_path(binary_path)}")

    code_size_info = build_code_size_info(
        estimated_code_size,
        exact_code_size,
        emit_c_only=emit_c_only,
        is_library=is_library,
        fallback_reason=code_size_fallback_reason,
    )
    total_program_size = runtime_memory_size + (code_size_info.exact_bytes or 0)

    print("\n" + "="*70)
    print("RESOURCE ANALYSIS")
    print("="*70)
    
    if show_resources:
        # Detailed per-function view
        for module_name in modules.keys():
            print(f"\nModule: {module_name}")
            print("-" * 70)
            
            all_resources = program_resources.get_module_resources(module_name)
            if not all_resources:
                print("  (no functions)")
                continue
            
            for func_name, resource in all_resources.items():
                print(f"\n  Function: {func_name}()")
                print(f"    Frame:     {resource.frame_stack_bytes:6d} bytes")
                print(f"    Stack:     {resource.stack_bytes:6d} bytes")
                print(f"    Heap:      {resource.heap_bytes:6d} bytes")
                print(f"    Storage:   {resource.storage_bytes:6d} bytes / {resource.storage_objects:3d} objects")
                if resource.recursion_depth is not None:
                    print(f"    Recursion: depth {resource.recursion_depth}")
                print(f"    Deterministic: {'yes' if resource.deterministic else 'no'}")
                print(f"    ISR-safe:      {'yes' if resource.isr_safe else 'no'}")
                print(f"    Blocking:      {'yes' if resource.blocking else 'no'}")
                print(f"    Allocates:     {'yes' if resource.allocates else 'no'}")
                print(f"    Reentrant:     {'yes' if resource.reentrant else 'no'}")
                print(f"    May fail:      {'yes' if resource.may_fail else 'no'}")
                print(f"    Uses timer:    {'yes' if resource.uses_timer else 'no'}")
                if resource.is_interrupt:
                    print(f"    Interrupt:     yes")
                if resource.is_task:
                    print(f"    Task:          yes ({resource.task_stack_bytes}B stack)")
                if resource.call_path:
                    print(f"    Deepest path:  {' -> '.join(resource.call_path)}")
    
    print(f"\nProgram Size Summary:")
    print(f"  Stack (max):   {total_stack:8d} bytes")
    print(f"  Heap (total):  {total_heap:8d} bytes")
    print(f"  Task stack:    {total_task_stack:8d} bytes")
    print(f"  Storage use:   {total_storage_bytes:8d} bytes / {total_storage_objects} objects")
    print(f"  {code_size_info.summary_label}: {code_size_info.display_bytes:8d} bytes")
    print(f"  -------------------------------")
    if code_size_info.exact_bytes is not None:
        print(f"  TOTAL:         {total_program_size:8d} bytes ({total_program_size / 1024:.2f} KB)")
    else:
        estimated_total = runtime_memory_size + code_size_info.display_bytes
        print(f"  Runtime total: {runtime_memory_size:8d} bytes ({runtime_memory_size / 1024:.2f} KB)")
        print(f"  Total + est.:  {estimated_total:8d} bytes ({estimated_total / 1024:.2f} KB)")
    if deepest_path:
        print(f"  Deepest path:  {' -> '.join(deepest_path)}")
    recursive_cycles = program_resources.get_recursive_cycles()
    if recursive_cycles:
        print(f"  Call cycles:   {len(recursive_cycles)}")
    if code_size_info.note:
        print(f"  Note:          {code_size_info.note}")
    print("="*70)

    if max_memory_declared:
        if code_size_info.exact_bytes is not None:
            if total_program_size > max_memory_declared:
                print(f"\n" + "!"*70, file=sys.stderr)
                print(f"ERROR: Program exceeds declared memory budget!", file=sys.stderr)
                print(f"!"*70, file=sys.stderr)
                print(
                    f"\n  Declared max_memory: {max_memory_declared:8d} bytes ({max_memory_declared / 1024:.2f} KB)",
                    file=sys.stderr,
                )
                print(
                    f"  Actual program size: {total_program_size:8d} bytes ({total_program_size / 1024:.2f} KB)",
                    file=sys.stderr,
                )
                print(
                    f"  Overflow:            {total_program_size - max_memory_declared:8d} bytes",
                    file=sys.stderr,
                )
                print(
                    f"\nEither reduce program size or increase #[max_memory(SIZE)].",
                    file=sys.stderr,
                )
                return 1

            used_percent = (total_program_size / max_memory_declared) * 100
            remaining = max_memory_declared - total_program_size
            print(f"\nMemory Budget: {total_program_size}/{max_memory_declared} bytes ({used_percent:.1f}% used)")
            print(f"Remaining:     {remaining} bytes ({remaining / 1024:.2f} KB)")
            print("[OK] Program fits within declared memory budget\n")
        else:
            if runtime_memory_size > max_memory_declared:
                print(f"\n" + "!"*70, file=sys.stderr)
                print(f"ERROR: Runtime memory exceeds declared memory budget!", file=sys.stderr)
                print(f"!"*70, file=sys.stderr)
                print(
                    f"\n  Declared max_memory: {max_memory_declared:8d} bytes ({max_memory_declared / 1024:.2f} KB)",
                    file=sys.stderr,
                )
                print(
                    f"  Runtime memory use:  {runtime_memory_size:8d} bytes ({runtime_memory_size / 1024:.2f} KB)",
                    file=sys.stderr,
                )
                print(
                    f"  Overflow:            {runtime_memory_size - max_memory_declared:8d} bytes",
                    file=sys.stderr,
                )
                print(
                    f"\nLink the program to measure code size, or reduce runtime memory usage.",
                    file=sys.stderr,
                )
                return 1

            used_percent = (runtime_memory_size / max_memory_declared) * 100
            remaining = max_memory_declared - runtime_memory_size
            print(
                f"\nMemory Budget (runtime only): {runtime_memory_size}/{max_memory_declared} bytes ({used_percent:.1f}% used)"
            )
            print(f"Remaining:                  {remaining} bytes ({remaining / 1024:.2f} KB)")
            print("Code bytes were not enforced because no linked artifact was produced.\n")

    max_storage_declared = sum(
        module.directives.get("max_storage", 0)
        for name, module in modules.items()
        if name not in stdlib_modules
    )
    if max_storage_declared:
        if total_storage_bytes > max_storage_declared:
            print("error: program exceeds declared persistent storage budget", file=sys.stderr)
            print(f"  Declared max_storage: {max_storage_declared} bytes", file=sys.stderr)
            print(f"  Actual storage use:   {total_storage_bytes} bytes", file=sys.stderr)
            return 1
        print(f"Storage Budget: {total_storage_bytes}/{max_storage_declared} bytes")

    max_storage_objects_declared = sum(
        module.directives.get("max_storage_objects", 0)
        for name, module in modules.items()
        if name not in stdlib_modules
    )
    if max_storage_objects_declared:
        if total_storage_objects > max_storage_objects_declared:
            print("error: program exceeds declared persistent object budget", file=sys.stderr)
            print(f"  Declared max_storage_objects: {max_storage_objects_declared}", file=sys.stderr)
            print(f"  Actual storage objects:       {total_storage_objects}", file=sys.stderr)
            return 1
        print(f"Storage Objects: {total_storage_objects}/{max_storage_objects_declared}")

    max_task_stack_declared = sum(
        module.directives.get("max_task_stack", 0)
        for name, module in modules.items()
        if name not in stdlib_modules
    )
    if max_task_stack_declared:
        if total_task_stack > max_task_stack_declared:
            print("error: program exceeds declared task stack budget", file=sys.stderr)
            print(f"  Declared max_task_stack: {max_task_stack_declared} bytes", file=sys.stderr)
            print(f"  Actual task stack use:  {total_task_stack} bytes", file=sys.stderr)
            return 1
        print(f"Task Stack Budget: {total_task_stack}/{max_task_stack_declared} bytes")

    if target_config:
        validation_error = target_config.validate_resources(
            total_stack,
            total_heap,
            code_size=None,
        )

        if validation_error:
            print(f"error: target resource limits exceeded:", file=sys.stderr)
            print(f"\n{target_config.get_limits_summary()}", file=sys.stderr)
            print(f"\nUsage:", file=sys.stderr)
            print(f"  Stack: {total_stack}B", file=sys.stderr)
            print(f"  Heap:  {total_heap}B", file=sys.stderr)
            print(f"\n{validation_error}", file=sys.stderr)
            return 1

        print(f"\n[OK] Resource validation passed for target: {target_config.target.name}")
        print(f"  Stack: {total_stack}B / {target_config.target.stack_bytes}B")
        print(f"  Heap:  {total_heap}B")
        print(f"  Code:  not validated (target artifact size unavailable)")

    if emit_c_only or is_library:
        return 0
    
    # ========================================================================
    # Run executable if --run
    # ========================================================================
    
    if run_after:
        print(f"\nRunning {to_native_tool_path(binary_path)}...")
        print("=" * 70)
        try:
            result = subprocess.run([to_native_tool_path(binary_path)])
            return result.returncode
        except Exception as e:
            print(f"error: failed to run executable: {e}", file=sys.stderr)
            return 1
    
    return 0


def main():
    """Main entry point for BASIS compiler CLI."""
    
    parser = argparse.ArgumentParser(
        prog='basis',
        description='BASIS Compiler - Compile BASIS source files to executable binaries',
        epilog='Example: basis build main.bs math.bs -o output --run'
    )
    
    parser.add_argument(
        'command',
        help='Compiler command (currently only "build" is supported)'
    )
    
    parser.add_argument(
        'files',
        nargs='+',
        metavar='FILE',
        help='BASIS source files (.bs) to compile'
    )
    
    parser.add_argument(
        '-o',
        dest='output',
        metavar='DIR',
        default='./build',
        help='Output directory for generated files (default: ./build)'
    )
    
    parser.add_argument(
        '--emit-c',
        action='store_true',
        help='Only generate C code, do not compile with gcc'
    )
    
    parser.add_argument(
        '--run',
        action='store_true',
        help='Run the compiled binary after successful compilation'
    )
    
    parser.add_argument(
        '--target',
        metavar='TARGET',
        default='host',
        help=f'Target platform (default: host). Available: {", ".join(PREDEFINED_TARGETS.keys())}'
    )
    
    parser.add_argument(
        '--target-config',
        metavar='FILE',
        help='Custom target configuration JSON file'
    )
    
    parser.add_argument(
        '--show-resources',
        action='store_true',
        help='Show detailed resource usage analysis'
    )
    
    parser.add_argument(
        '--lib',
        action='store_true',
        help='Build as library (main() function optional)'
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Validate command
    if args.command != 'build':
        print(f"error: unknown command '{args.command}'. Only 'build' is supported.", 
              file=sys.stderr)
        parser.print_help(file=sys.stderr)
        return 1
    
    # Validate files
    if not args.files:
        print("error: no input files specified", file=sys.stderr)
        parser.print_help(file=sys.stderr)
        return 1
    
    # Load target configuration
    target_config = None
    if args.target_config:
        # Load from custom JSON file
        try:
            target_config = TargetConfig.from_file(args.target_config)
            print(f"Loaded target configuration from {args.target_config}")
        except FileNotFoundError:
            print(f"error: target configuration file not found: {args.target_config}", 
                  file=sys.stderr)
            return 1
        except Exception as e:
            print(f"error: failed to load target configuration: {e}", 
                  file=sys.stderr)
            return 1
    elif args.target != 'host':
        # Use predefined target
        try:
            target_config = TargetConfig.from_name(args.target)
            print(f"Using predefined target: {args.target}")
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            print(f"Available targets: {', '.join(PREDEFINED_TARGETS.keys())}", 
                  file=sys.stderr)
            return 1
    
    # Run compilation pipeline
    try:
        exit_code = compile_basis(
            args.files,
            args.output,
            args.emit_c,
            args.run,
            target_config,
            args.show_resources,
            args.lib,
            stdlib_path=None  # Use default stdlib discovery
        )
        return exit_code
    except KeyboardInterrupt:
        print("\nCompilation interrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"error: internal compiler error: {e}", file=sys.stderr)
        # In production mode, don't show stack traces
        # For debugging, you can enable this:
        # import traceback
        # traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
