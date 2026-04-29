from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "compiler"))

from bir.lower import LoweringInput, lower_validated_program
from bir.model import ProgramRuntime
from diagnostics import DiagnosticEngine
from target_config import TargetConfig
from lexer import Lexer
from parser import Parser
from sema import ModuleRegistry, SemanticAnalyzer
from typecheck import TypeChecker
from consteval import evaluate_constants
from loop_analysis import analyze_loops
from resource_analysis import analyze_program_resources


def build_bir_program(source: str, module_name: str = "sample", target_id: str = "host"):
    diag = DiagnosticEngine()
    registry = ModuleRegistry()
    registry.register_known_module(module_name)

    lexer = Lexer(source, filename=f"{module_name}.bs", diag_engine=diag)
    tokens = lexer.tokenize()
    assert not diag.has_errors(), "lexer unexpectedly failed"

    parser = Parser(tokens, filename=f"{module_name}.bs", diag_engine=diag)
    module = parser.parse(module_name)
    assert module is not None, "parser returned no module"
    assert not diag.has_errors(), "parser unexpectedly failed"

    analyzer = SemanticAnalyzer(diag, registry)
    assert analyzer.analyze(module), "semantic analysis unexpectedly failed"
    assert analyzer.module_scope is not None
    registry.register_module(module_name, analyzer.module_scope.symbols)

    type_checker = TypeChecker(diag, analyzer.module_scope)
    assert type_checker.check(module), "type checking unexpectedly failed"

    const_eval = evaluate_constants(module, diag, type_checker)
    loop_analyzer = analyze_loops(module, diag, const_eval, analyzer.module_scope)
    program_resources = analyze_program_resources(
        {module_name: module},
        diag,
        {module_name: analyzer.module_scope},
        {module_name: type_checker},
        {module_name: const_eval},
        {module_name: loop_analyzer},
    )
    assert not diag.has_errors(), "validation pipeline reported unexpected errors"

    target = TargetConfig.from_name(target_id).target
    return lower_validated_program(
        LoweringInput(
            program_name="sample_program",
            target=target_id,
            profile="relaxed",
            entry_module=module_name,
            entry_function="main",
            runtime=ProgramRuntime(
                target_id=target_id,
                target_triple=target.triple,
                target_abi=target.abi,
                startup_model="hosted" if target_id == "host" else "target_alias",
                entry_symbol="main" if target_id == "host" else "app_main",
                internal_entry_symbol=f"basis_entry__{module_name}__main",
                entry_return="i32" if target_id == "host" else "void",
                supports_host_run=(target_id == "host"),
            ),
            modules={module_name: module},
            module_paths={module_name: f"tests/cases/{module_name}.bs"},
            type_checkers={module_name: type_checker},
            const_evaluators={module_name: const_eval},
            loop_analyzers={module_name: loop_analyzer},
            program_resources=program_resources,
        )
    )
