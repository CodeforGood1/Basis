# BASIS

> **BASIS** is a deterministic, resource-aware systems programming language for embedded development.

BASIS is built for the kind of embedded software that becomes difficult to trust as projects grow: hidden heap growth, stack surprises, unsafe interrupt behavior, and foreign-function calls whose runtime behavior is unclear. Instead of treating those as late debugging problems, BASIS tries to push more of them into compile-time analysis.

Today BASIS compiles to C. The long-term goal is not to replace every systems language, but to provide a constrained environment where critical embedded logic is easier to reason about, bound, test, and integrate with existing C firmware.

## What BASIS Looks Like

```basis
#[max_memory(256kb)]

import core::*;
import io::*;

fn main() -> i32 {
    let x: i32 = abs_i32(-42);
    out_i32(x);
    println("");
    return 0;
}
```

## What It Focuses On

- deterministic, bounded control flow
- explicit memory budgets per module
- whole-program call-graph stack analysis
- bounded heap/resource accounting
- interrupt-safe code validation
- explicit foreign-function effect contracts
- C code generation for host and embedded integration

## Current State

BASIS already has:
- its own lexer, parser, semantic analysis, and type checker
- compile-time resource analysis
- no `while` loops; only bounded `for` loops remain
- bounded recursion through `@recursion(max=N)`
- interrupt handlers through `@interrupt`
- explicit foreign-call contracts such as `@deterministic`, `@blocking`, `@allocates`, and `@isr_safe`
- a C backend and local examples/tests

It is best understood today as a serious embedded language prototype moving toward a usable language platform.

## Getting Started

### Requirements

- Python 3
- `gcc` in `PATH` for host builds

### Clone

```bash
git clone https://github.com/CodeforGood1/Basis.git
cd Basis
```

### First Build

```bash
python compiler/basis.py build examples/hello.bs --run
```

### Emit C Only

```bash
python compiler/basis.py build examples/hello.bs --emit-c
```

### Show Resource Analysis

```bash
python compiler/basis.py build examples/callgraph_demo.bs --show-resources --run
```

### Verify the Install

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_local_checks.ps1
```

### Optional: Make `basis` Easy to Run

If you want a shell command instead of calling Python directly, add the repo's `compiler` folder to your `PATH` and use the provided launcher script on Windows.

### Build as a C-Linked Library

```bash
python compiler/basis.py build --lib examples/isr_demo.bs --emit-c --target esp32
```

This generates C output that can be linked into an existing C or embedded firmware project.

## Deployment / Use Modes

There are two main ways to use BASIS today:

### 1. Host Executable

Use BASIS as a normal compiled language on your machine:

```bash
python compiler/basis.py build my_program.bs --run
```

### 2. Embedded / C Integration

Use BASIS as a constrained logic layer that compiles to C:

```bash
python compiler/basis.py build --lib control.bs --emit-c --target esp32
```

Then compile the generated C with your existing firmware stack, HAL, or SDK.

## Key Features

### Explicit Memory Budget

Every BASIS file declares a maximum memory budget:

```basis
#[max_memory(256kb)]
#[max_memory(32kb)]
#[max_memory(512b)]
```

### Compile-Time Resource Analysis

The compiler reports stack, heap, code-size estimate, and deepest call path:

```
======================================================================
RESOURCE ANALYSIS
======================================================================

Program Size Summary:
  Stack (max):         20 bytes
  Heap (total):       512 bytes
  Code (~):           700 bytes
  -------------------------------
  TOTAL:             1232 bytes (1.20 KB)
  Deepest path:  main -> filter -> accumulate
======================================================================
```

### Static Safety Checks

- array bounds checks
- bounded recursion checks
- whole-program stack checks
- heap size checks
- interrupt validation
- explicit foreign-function contracts

## Documentation Index

| Document | Description |
|----------|-------------|
| [compiler/syntax.md](compiler/syntax.md) | Complete language syntax reference |
| [compiler/safeguards.md](compiler/safeguards.md) | Safety guarantees and compile-time checks |
| [compiler/limitations.md](compiler/limitations.md) | Known limitations and workarounds |

---

## Safety Errors

| Error | Meaning |
|-------|---------|
| `E_INDEX_OUT_OF_BOUNDS` | Array access exceeds declared size |
| `E_UNBOUNDED_LOOP` | Loop without determinable bound |
| `E_WHILE_REMOVED` | `while` loops are not part of BASIS |
| `E_MISSING_RECURSION_ANNOTATION` | Recursive function needs `@recursion(max=N)` |
| `E_UNBOUNDED_HEAP` | Allocation size not compile-time constant |
| `E_EXTERN_STACK_REQUIRED` | `extern fn` is missing `@stack(N)` |
| `E_EXTERN_EFFECT_REQUIRED` | `extern fn` must declare `@deterministic` or `@nondeterministic` |
| `E_EXTERN_ALLOCATES_BUDGET_REQUIRED` | generic `extern fn` with `@allocates` needs `@allocates(max=N)` |
| `E_EFFECT_CONFLICT` | incompatible effect annotations were combined |
| `E_INTERRUPT_SIGNATURE` | `@interrupt` handler has invalid signature |
| `E_INTERRUPT_BLOCKING` | `@interrupt` handler calls blocking code |
| `E_MISSING_RETURN` | Function must return value on all paths |
| `E_INVALID_RETURN_TYPE` | Cannot return arrays by value |
| `missing #[max_memory]` | File lacks memory directive |
| `Program exceeds declared memory budget` | Total usage > declared max |

---

## Examples

### Bounded Recursion
```basis
@recursion(max=10)
fn factorial(n: i32) -> i32 {
    if n <= 1 { return 1; }
    return n * factorial(n - 1);
}
```

### Heap Allocation
```basis
import mem::*;

fn main() -> i32 {
    let buffer: *u8 = alloc_bytes(256 as u32);
    free_bytes(buffer);
    return 0;
}
```

### Array Processing
```basis
fn sum(arr: [i32; 5]) -> i32 {
    let total: i32 = 0;
    for i in 0..5 {
        total = total + arr[i];
    }
    return total;
}
```

---

## Project Structure

```
compiler/
├── basis.py          # Main compiler driver
├── lexer.py          # Tokenization
├── parser.py         # Recursive descent parser
├── ast_defs.py       # AST node definitions
├── sema.py           # Semantic analysis
├── typecheck.py      # Type checking
├── consteval.py      # Constant evaluation
├── loop_analysis.py  # Loop bound analysis
├── resource_analysis.py  # Resource tracking
├── codegen.py        # Single-file C generation
├── module_codegen.py # Multi-module C generation
└── diagnostics.py    # Error reporting

stdlib/
├── core/core.bs
├── mem/mem.bs
├── io/io.bs
└── math/math.bs

examples/
├── hello.bs
└── test_io.bs
```

---

## Appendix: Extern and C ABI Specification

### Extern Declaration Syntax
```
@deterministic @isr_safe @stack(N) extern fn IDENTIFIER(param_list?) -> type;
@deterministic @blocking @stack(N) extern fn IDENTIFIER(param_list?) -> type;
@deterministic @allocates(max=N) @stack(N) extern fn IDENTIFIER(param_list?) -> type;
@nondeterministic @blocking @stack(N) extern fn IDENTIFIER(param_list?) -> type = "symbol_name";
param_list ::= param ("," param)*
param ::= IDENTIFIER ":" type
```
- Allowed types: i8, i16, i32, i64, u8, u16, u32, u64, f32, f64, bool, void return; raw pointers to any allowed type; pointers to structs; structs by value only if trivially C-compatible.
- Forbidden in extern signatures: arrays, slices, function pointers, opaque handles, managed/high-level types.
- Variadic functions: forbidden.
- `@stack(N)` is required on every extern so the whole-program call graph stays bounded.
- Every extern must declare exactly one determinism contract: `@deterministic` or `@nondeterministic`.
- `@blocking`, `@allocates(max=N)`, and `@isr_safe` are optional refinements.
- `@isr_safe` cannot be combined with `@blocking`, `@allocates`, or `@nondeterministic`.
- Bare `@allocates` is only valid for compiler-known allocator models such as `malloc`; generic foreign allocators must use `@allocates(max=N)`.

### Name Binding Rules
- Default symbol name = BASIS identifier, case-sensitive, no mangling.
- Aliasing: optional `= "symbol_name"` binds to the exact C symbol literal.
- No implicit decoration or namespaces.

### Calling Convention
- Always platform C ABI.
- Parameters passed per platform C ABI; no hidden args.
- Returns: scalars/pointers per C ABI; structs by value only if ABI supports it (else rejected). Hidden sret may be used by ABI; if unsupported, reject.
- No exceptions/unwinding across the boundary.

### Memory & Ownership Rules
- No implicit allocation or freeing by the compiler.
- No ownership transfer by default; caller retains ownership of pointers passed/received unless explicitly documented externally.
- Foreign heap behavior is explicit: `@allocates(max=N)` contributes to heap budgets, and compiler-known allocators are modeled directly at call sites.
- Blocking behavior is explicit: `@blocking` propagates through the call graph and disqualifies ISR use.
- Determinism across extern boundaries is explicit: `@deterministic` / `@nondeterministic` propagate through the call graph.

### Header Emission Rules
- Headers generated only for non-entry modules; entry (main) emits no header.
- Public externs appear in headers as non-static prototypes; private externs only in `.c` as static prototypes.
- Headers contain declarations only, never bodies. Own guard first, then standard includes, then imported module headers in lexicographic order.

### Symbol Visibility
- `public fn` -> prototype in header, definition in `.c` (non-static).
- `private fn` -> no header prototype; definition in `.c` as static.
- `extern fn` -> prototype only; no definition. Public externs non-static in header; private externs static in `.c`. Entry `main` is never extern/static and no header is emitted for it.

### Diagnostics
- `E_EXTERN_TYPE`: invalid extern type in signature.
- `E_EXTERN_ALIAS`: invalid extern alias; expected string literal.
- `E_EXTERN_VARIADIC`: variadic externs are not supported.
- `E_EXTERN_STRUCTRET`: struct return not supported by target ABI.
- `E_EXTERN_BODY`: extern functions must not have bodies.
- `E_EXTERN_EFFECT_REQUIRED`: extern functions must declare `@deterministic` or `@nondeterministic`.
- `E_EXTERN_ALLOCATES_BUDGET_REQUIRED`: generic foreign allocators must use `@allocates(max=N)`.
- `E_EFFECT_CONFLICT`: incompatible effect annotations were combined.

## PART B — Compiler Responsibilities
- Store extern declarations (with optional alias) in symbol table.
- Type check externs like declared functions without bodies; validate parameter/return types.
- Exclude extern bodies from resource/loop analyses; analyze call sites using explicit effect contracts.
- Externs do not create module import dependencies.
- Emit C prototypes respecting visibility and aliasing; no bodies generated.

## PART C — Code Generation Rules
- Lowering: `extern fn foo(a: i32) -> i32;` -> `int32_t foo(int32_t a);`
- Aliasing: `extern fn local(a: i32) -> i32 = "c_symbol";` -> `int32_t local(int32_t a) __asm__("c_symbol");` (or equivalent alias mechanism; if unavailable, emit prototype named `c_symbol`).
- Struct pointer extern: `extern fn process(s: *MyStruct) -> i32;` -> `int32_t process(struct MyStruct* s);`
- No stubs/wrappers/thunks; direct calls only; zero overhead.

## PART D — Non-Goals (Forbidden)
- C++ ABI or name mangling.
- Automatic/reflective bindings.
- Implicit headers beyond stated rules.
- Runtime shims/trampolines/thunks.
- Foreign exception propagation or unwinding across the boundary.

## PART E — Implementation Checklist
- Extern symbols recorded in AST and symbol table with alias info.
- Externs participate in type checking; bodies forbidden.
- Externs excluded from resource/loop analyses beyond call-site effects.
- Extern effects participate in determinism, blocking, heap, and ISR-safety propagation.
- Public externs -> prototypes in headers; private externs -> static prototypes in `.c`.
- No code emitted for extern bodies; zero-overhead direct calls.
- ABI-compatible prototypes generated with correct C types and calling convention.
- Diagnostics enforced: `E_EXTERN_TYPE`, `E_EXTERN_ALIAS`, `E_EXTERN_VARIADIC`, `E_EXTERN_STRUCTRET`, `E_EXTERN_BODY`, `E_EXTERN_EFFECT_REQUIRED`, `E_EXTERN_ALLOCATES_BUDGET_REQUIRED`, `E_EFFECT_CONFLICT`.
