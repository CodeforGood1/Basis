from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "compiler"))

from diagnostics import DiagnosticEngine
from lexer import Lexer
from parser import Parser
from sema import ModuleRegistry, SemanticAnalyzer
from typecheck import TypeChecker
from consteval import evaluate_constants
from loop_analysis import analyze_loops
from resource_analysis import analyze_program_resources
from bir import render_bir, verify_program
from bir.lower import LoweringInput, lower_validated_program


def build_validated_program(source: str, module_name: str = "sample"):
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
    return module, type_checker, const_eval, loop_analyzer, program_resources


def assert_partial_lowering_works_for_straight_line_functions():
    source = """#[max_memory(4kb)]
public const LIMIT: i32 = 3;

@deterministic
@blocking
@stack(64)
extern fn print_i32(value: i32) -> void;

fn main() -> i32 {
    let value: i32 = 1 + 2;
    print_i32(value);
    return value;
}
"""

    module, type_checker, const_eval, loop_analyzer, program_resources = build_validated_program(source)
    bir_program = lower_validated_program(
        LoweringInput(
            program_name="sample_program",
            target="host",
            profile="relaxed",
            entry_module="sample",
            entry_function="main",
            modules={"sample": module},
            module_paths={"sample": "tests/cases/sample.bs"},
            type_checkers={"sample": type_checker},
            const_evaluators={"sample": const_eval},
            loop_analyzers={"sample": loop_analyzer},
            program_resources=program_resources,
        )
    )

    verify_program(bir_program)
    rendered = render_bir(bir_program)

    lowered_module = rendered["modules"][0]
    assert lowered_module["externs"][0]["abi"] == "c"
    assert lowered_module["functions"][0]["visibility"] == "entry"
    assert [export["name"] for export in lowered_module["exports"]] == ["LIMIT", "main"]
    assert lowered_module["globals"][0]["initializer"] == "3"
    instructions = lowered_module["functions"][0]["blocks"][0]["instructions"]
    assert [instruction["kind"] for instruction in instructions] == ["math", "store", "load", "call", "load"]
    assert instructions[0]["opcode"] == "+"
    assert instructions[3]["opcode"] == "print_i32"
    assert instructions[0]["metadata"]["source_loc"]["path"] == "tests/cases/sample.bs"


def assert_lowering_handles_control_flow_and_mutable_state():
    source = """#[max_memory(8kb)]
fn main() -> i32 {
    let total: i32 = 0;

    for i in 0..4 {
        if i == 2 {
            continue;
        }

        total = total + i;

        if total > 4 {
            break;
        }
    }

    if total > 0 {
        total = total + 1;
    } else {
        total = 99;
    }

    return total;
}
"""

    module, type_checker, const_eval, loop_analyzer, program_resources = build_validated_program(source)
    bir_program = lower_validated_program(
        LoweringInput(
            program_name="sample_program",
            target="host",
            profile="relaxed",
            entry_module="sample",
            entry_function="main",
            modules={"sample": module},
            module_paths={"sample": "tests/cases/sample.bs"},
            type_checkers={"sample": type_checker},
            const_evaluators={"sample": const_eval},
            loop_analyzers={"sample": loop_analyzer},
            program_resources=program_resources,
        )
    )

    verify_program(bir_program)
    rendered = render_bir(bir_program)
    lowered_function = rendered["modules"][0]["functions"][0]
    block_names = [block["name"] for block in lowered_function["blocks"]]
    assert any(name.startswith("for_cond_") for name in block_names)
    assert any(name.startswith("for_body_") for name in block_names)
    assert any(name.startswith("if_then_") for name in block_names)
    assert any(
        instruction["kind"] == "store" and instruction["opcode"] == "="
        for block in lowered_function["blocks"]
        for instruction in block["instructions"]
    )
    assert any(block["terminator"]["kind"] == "cond_br" for block in lowered_function["blocks"])
    assert any(
        target.startswith("for_exit_")
        for block in lowered_function["blocks"]
        for target in block["terminator"]["targets"]
    )


def assert_lowering_handles_aggregate_materialization():
    source = """#[max_memory(8kb)]
struct Pair {
    left: i32,
    right: i32,
}

fn main() -> i32 {
    let values: [i32; 4] = [1, 2, 3, 4];
    let repeated: [u8; 4] = [0 as u8; 4; 1: 7 as u8, 3: 9 as u8];
    let pair: Pair = Pair { left: values[1], right: values[3] };
    return pair.left + (repeated[1] as i32);
}
"""

    module, type_checker, const_eval, loop_analyzer, program_resources = build_validated_program(source)
    bir_program = lower_validated_program(
        LoweringInput(
            program_name="sample_program",
            target="host",
            profile="relaxed",
            entry_module="sample",
            entry_function="main",
            modules={"sample": module},
            module_paths={"sample": "tests/cases/sample.bs"},
            type_checkers={"sample": type_checker},
            const_evaluators={"sample": const_eval},
            loop_analyzers={"sample": loop_analyzer},
            program_resources=program_resources,
        )
    )

    verify_program(bir_program)
    lowered_function = render_bir(bir_program)["modules"][0]["functions"][0]
    instructions = [
        instruction
        for block in lowered_function["blocks"]
        for instruction in block["instructions"]
    ]
    assert any(instruction["opcode"] == "array_literal" for instruction in instructions)
    assert any(instruction["opcode"] == "array_repeat" for instruction in instructions)
    assert any(str(instruction["opcode"]).startswith("struct_literal:Pair") for instruction in instructions)
    assert any(instruction["kind"] == "insert" and instruction["opcode"] == "index" for instruction in instructions)
    assert any(instruction["kind"] == "insert" and instruction["opcode"] == "left" for instruction in instructions)


if __name__ == "__main__":
    assert_partial_lowering_works_for_straight_line_functions()
    assert_lowering_handles_control_flow_and_mutable_state()
    assert_lowering_handles_aggregate_materialization()
    print("BIR lowering regression checks passed.")
