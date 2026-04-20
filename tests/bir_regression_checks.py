import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bir import (
    Block,
    BirVerificationError,
    Extern,
    Function,
    FunctionAttrs,
    FunctionEffects,
    FunctionResources,
    Global,
    Import,
    Instruction,
    InstructionMetadata,
    Module,
    ModuleAttrs,
    ModuleResources,
    Param,
    Program,
    SourceLoc,
    SymbolRef,
    Terminator,
    Type,
    ValueRef,
    render_bir,
    verify_program,
)


def scalar(kind: str) -> Type:
    return Type(kind=kind)


def build_sample_program() -> Program:
    i32 = scalar("i32")
    u32 = scalar("u32")
    void = scalar("void")
    loc = SourceLoc(
        path="tests/cases/sample.bs",
        line=4,
        column=5,
        end_line=4,
        end_column=24,
    )

    return Program(
        name="sample_program",
        target="host",
        profile="strict",
        entry=SymbolRef(module="sample", name="main"),
        modules=[
            Module(
                name="sample",
                source_path="tests/cases/sample.bs",
                attrs=ModuleAttrs(
                    max_memory=4096,
                    max_storage=256,
                    max_storage_objects=4,
                    strict=True,
                ),
                imports=[Import(module_name="io", items=["print_i32"])],
                exports=[SymbolRef(module="sample", name="main")],
                globals=[
                    Global(
                        name="boot_count",
                        visibility="private",
                        type=u32,
                        initializer="0",
                    )
                ],
                functions=[
                    Function(
                        name="main",
                        visibility="entry",
                        params=[],
                        returns=i32,
                        attrs=FunctionAttrs(
                            deterministic=True,
                            reentrant=True,
                            isr_safe=True,
                        ),
                        effects=FunctionEffects(
                            deterministic=True,
                            blocking=False,
                            allocates=None,
                            uses_storage=False,
                            isr_safe=True,
                        ),
                        resources=FunctionResources(stack_max=32, heap_max=0),
                        blocks=[
                            Block(
                                name="entry",
                                instructions=[
                                    Instruction(
                                        kind="call",
                                        opcode="print_i32",
                                        result=ValueRef("tmp0"),
                                        operands=[ValueRef("print_i32"), ValueRef("boot_count")],
                                        type=void,
                                        metadata=InstructionMetadata(
                                            source_loc=loc,
                                            effect_notes=["deterministic call"],
                                            resource_notes=["stack accounted"],
                                        ),
                                    )
                                ],
                                terminator=Terminator(
                                    kind="ret",
                                    operands=[ValueRef("zero")],
                                ),
                            )
                        ],
                    )
                ],
                externs=[
                    Extern(
                        name="print_i32",
                        visibility="public",
                        params=[Param(name="value", type=i32)],
                        returns=void,
                        abi="c",
                        symbol_name="print_i32",
                        attrs=FunctionAttrs(
                            deterministic=True,
                            blocking=True,
                            reentrant=False,
                            isr_safe=False,
                        ),
                        effects=FunctionEffects(
                            deterministic=True,
                            blocking=True,
                            allocates=None,
                            uses_storage=False,
                            isr_safe=False,
                        ),
                        resources=FunctionResources(stack_max=64, heap_max=0),
                    )
                ],
                resources=ModuleResources(
                    stack_max=32,
                    heap_max=0,
                    storage_max=0,
                    code_size_estimate=128,
                    deepest_call_path=[SymbolRef(module="sample", name="main")],
                ),
            )
        ],
    )


def assert_snapshot_matches():
    program = build_sample_program()
    verify_program(program)

    actual = render_bir(program)
    snapshot_path = ROOT / "tests" / "snapshots" / "bir_sample_program.json"
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if actual != expected:
        raise AssertionError(
            "BIR snapshot mismatch.\n"
            f"Expected:\n{json.dumps(expected, indent=2)}\n"
            f"Actual:\n{json.dumps(actual, indent=2)}"
        )


def assert_verifier_rejects_invalid_program():
    bad_program = Program(
        name="bad",
        target="host",
        profile="strict",
        entry=SymbolRef(module="bad", name="main"),
        modules=[
            Module(
                name="bad",
                source_path="bad.bs",
                attrs=ModuleAttrs(max_memory=1024),
                functions=[
                    Function(
                        name="main",
                        visibility="entry",
                        params=[],
                        returns=scalar("i32"),
                        attrs=FunctionAttrs(deterministic=True),
                        effects=FunctionEffects(
                            deterministic=True,
                            blocking=False,
                            allocates=None,
                            uses_storage=False,
                            isr_safe=True,
                        ),
                        resources=FunctionResources(stack_max=8, heap_max=0),
                        blocks=[
                            Block(
                                name="entry",
                                instructions=[],
                                terminator=Terminator(kind="br", targets=["missing"]),
                            )
                        ],
                    )
                ],
            )
        ],
    )

    try:
        verify_program(bad_program)
    except BirVerificationError as exc:
        if "missing" not in str(exc):
            raise AssertionError(f"unexpected verifier error: {exc}") from exc
        return
    raise AssertionError("expected verifier to reject invalid control flow")


if __name__ == "__main__":
    assert_snapshot_matches()
    assert_verifier_rejects_invalid_program()
    print("BIR regression checks passed.")
