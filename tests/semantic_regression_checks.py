from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "compiler"))

from diagnostics import DiagnosticEngine
from lexer import Lexer
from parser import Parser
from sema import ModuleRegistry, SemanticAnalyzer


def parse_module(name: str, source: str, diag: DiagnosticEngine):
    lexer = Lexer(source, filename=f"{name}.bs", diag_engine=diag)
    tokens = lexer.tokenize()
    assert not diag.has_errors(), "lexer unexpectedly failed"

    parser = Parser(tokens, filename=f"{name}.bs", diag_engine=diag)
    module = parser.parse(name)
    assert module is not None, "parser returned no module"
    assert not diag.has_errors(), "parser unexpectedly failed"
    return module


def assert_unknown_module_is_reported():
    diag = DiagnosticEngine()
    registry = ModuleRegistry()

    assert not registry.module_exists("ghost")

    module = parse_module(
        "main",
        "#[max_memory(4kb)]\nimport ghost::*;\nfn main() -> i32 { return 0; }\n",
        diag,
    )

    analyzer = SemanticAnalyzer(diag, registry)
    assert not analyzer.analyze(module), "semantic analysis unexpectedly succeeded"
    assert any(d.err_code == "E_UNKNOWN_MODULE" for d in diag.diagnostics), (
        "expected E_UNKNOWN_MODULE from semantic analysis"
    )


def assert_discovered_modules_are_tracked():
    registry = ModuleRegistry()
    registry.register_known_module("math")
    assert registry.module_exists("math")


if __name__ == "__main__":
    assert_unknown_module_is_reported()
    assert_discovered_modules_are_tracked()
    print("semantic regression checks passed.")
