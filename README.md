# BASIS

> **BASIS** is a deterministic, resource-aware systems programming language for embedded development.

BASIS is designed for firmware and embedded logic that must stay bounded, predictable, and easier to reason about as systems grow. It focuses on classes of problems that often remain hidden until integration or long running field use, such as unclear stack growth, hidden heap usage, unsafe interrupt paths, and foreign calls whose behavior is not explicit.

Today BASIS validates programs through its own frontend and lowers them through a shared internal BIR layer. It has a stable C backend, a real LLVM backend that emits verified `.ll` plus host binaries for supported host targets, and an MLIR backend that preserves `.mlir` / `.llvm.mlir` artifacts while also producing real LLVM/object outputs for the same supported matrix. The goal is to provide a constrained programming model where important properties of embedded code can be checked earlier, reported clearly, and integrated into existing C-based projects without requiring a completely separate runtime ecosystem.

If you are new to the project, start with [LEARN.md](LEARN.md) for a guided introduction before moving to the full reference documentation.

## Why BASIS

Embedded software often compiles successfully long before it becomes easy to trust. As features accumulate, projects can become harder to reason about because resource usage, call depth, interrupt safety, and foreign boundary behavior are spread across multiple files and libraries.

BASIS approaches that problem by making these concerns part of the language and compiler model. Instead of leaving them entirely to manual review and late testing, the compiler performs static checks and resource analysis so more issues can be surfaced before code reaches hardware.

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
- persistent-storage budgeting
- interrupt-safe code validation
- task entry-point validation
- strict deterministic module profiles
- rollover-safe time helpers
- MMIO-oriented `volatile` register access
- bit and register helper libraries
- fixed-size checksum and byte queue libraries
- explicit foreign-function effect contracts
- C code generation for host and embedded integration
- LLVM IR emission through validated BIR lowering
- generated target build/flash bundles for embedded targets

## Implemented Capabilities

BASIS currently provides the following language and compiler capabilities:

- a complete front end with lexing, parsing, semantic analysis, type checking, constant evaluation, and C code generation
- deterministic control flow rules with `while` removed, bounded `for` loops, and bounded recursion through `@recursion(max=N)`
- explicit per-module memory budgets through `#[max_memory(...)]`
- whole-program resource analysis covering stack, heap, task stack, persistent storage, estimated code size, and deepest call path
- strict deterministic profiles through `#[strict]`
- interrupt handlers through `@interrupt`
- task entry points through `@task(stack=N, priority=N)`
- persistent storage budgeting through `#[max_storage(...)]`, `#[max_storage_objects(...)]`, and `@storage(...)`
- foreign-function contracts through annotations such as `@deterministic`, `@nondeterministic`, `@blocking`, `@allocates`, `@storage`, `@reentrant`, `@uses_timer`, `@may_fail`, and `@isr_safe`
- rollover-safe time helpers in `stdlib/time`
- volatile MMIO helpers in `stdlib/mmio`
- register, checksum, and fixed queue helpers in `stdlib/bits`, `stdlib/crc`, and `stdlib/ring`
- local examples, negative tests, and a release packaging flow for Windows

## Backend Status

- `--backend=c`: stable production backend and default path
- `--backend=llvm`: real LLVM IR, verified host object generation, and host `--run` support on the supported toolchain matrix
- `--backend=mlir`: real backend path that preserves MLIR artifacts and also emits LLVM IR/object outputs for the supported matrix

## Target Bundles

Every successful build now emits a `basis-target-manifest.json` alongside wrapper scripts such as:

- `basis-build-target.ps1`
- `basis-build-target.sh`
- `basis-flash-target.ps1`
- `basis-flash-target.sh`
- `basis-validate-target.ps1`
- `basis-validate-target.sh`

These files describe the target triple, ABI, build system, expected startup objects, linker-script requirements, flash command, required tools, and required support files for the selected target. Current built-in target profiles include:

- `host`
- `embedded_linux`
- `esp32`
- `stm32`
- `rp2040`

For ESP32 C builds, BASIS also generates an ESP-IDF project scaffold under `esp32_project/`. For bare-metal targets such as STM32 and RP2040, BASIS generates `target-support/` scaffolding for linker scripts and startup objects that must be completed with board-specific inputs before building a final image. The validation scripts fail fast when required external tools or support files are missing, so the generated bundle can be checked before a build or flash attempt.

BASIS is an embedded systems language under active development, with a working compiler, a static analysis pipeline, a growing standard library, and verified source and packaged workflows.

## Standard Library

The current standard library is intentionally small and targeted at deterministic embedded work:

- `core` for basic numeric helpers, boolean helpers, assertions, and swaps
- `io` for printing and basic host-side input
- `mem` for explicit heap and memory operations
- `math` for integer math and scaling helpers
- `string` for C-style string functions
- `time` for rollover-safe tick and deadline logic
- `mmio` for volatile register access
- `bits` for masks, packed fields, and alignment
- `crc` for fixed-size checksum and CRC helpers
- `ring` for fixed-size byte queues

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

### Emit LLVM IR

```bash
python compiler/basis.py build examples/hello.bs --backend llvm --emit-c
```

### Show Resource Analysis

```bash
python compiler/basis.py build examples/callgraph_demo.bs --show-resources --run
```

### Explore Embedded-Oriented Features

```bash
python compiler/basis.py build examples/time_demo.bs --run
python compiler/basis.py build examples/task_demo.bs --show-resources --emit-c
python compiler/basis.py build examples/storage_demo.bs --show-resources --emit-c
python compiler/basis.py build examples/mmio_demo.bs --emit-c --target esp32
python compiler/basis.py build examples/bits_demo.bs --run
python compiler/basis.py build examples/crc_demo.bs --run
python compiler/basis.py build examples/ring_demo.bs --run
```

### Verify the Install

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_local_checks.ps1
```

To also verify the packaged Windows release flow:

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_local_checks.ps1 -VerifyPackage
```

### Build a Windows Release Package

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 -Clean -Package
```

This creates a versioned distribution directory and ZIP archive containing the compiler, examples, standard library, and documentation.

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

For embedded workflows, BASIS now also emits target build bundles so the selected backend output can be driven through the target toolchain with generated wrapper scripts and a machine-readable manifest. In practice, BASIS can be used to compile analyzable application logic into C or LLVM IR and then hand it to an ESP-IDF, STM32, RP2040, or embedded-Linux toolchain while keeping the language frontend as the semantic source of truth.

## Key Features

### Explicit Memory Budget

Every BASIS file declares a maximum memory budget:

```basis
#[max_memory(256kb)]
#[max_memory(32kb)]
#[max_memory(512b)]
```

### Compile-Time Resource Analysis

The compiler reports stack, heap, task-stack, storage usage, code-size estimate, and deepest call path:

```
======================================================================
RESOURCE ANALYSIS
======================================================================

Program Size Summary:
  Stack (max):         20 bytes
  Heap (total):       512 bytes
  Task stack:        1024 bytes
  Storage use:        256 bytes / 2 objects
  Code (~):           700 bytes
  -------------------------------
  TOTAL:             2256 bytes (2.20 KB)
  Deepest path:  main -> filter -> accumulate
======================================================================
```

### Static Safety Checks

- array bounds checks
- bounded recursion checks
- whole-program stack checks
- heap size checks
- persistent-storage budget checks
- interrupt validation
- task entry-point validation
- strict module validation
- explicit foreign-function contracts

## Documentation Index

| Document | Description |
|----------|-------------|
| [compiler/syntax.md](compiler/syntax.md) | Complete language syntax reference |
| [compiler/safeguards.md](compiler/safeguards.md) | Safety guarantees and compile-time checks |
| [compiler/limitations.md](compiler/limitations.md) | Known limitations and workarounds |
| [LEARN.md](LEARN.md) | Guided introduction for new users |

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
| `E_STORAGE_CONTRACT_REQUIRED` | `@storage` must declare bytes and/or object budgets |
| `E_EFFECT_CONFLICT` | incompatible effect annotations were combined |
| `E_INTERRUPT_SIGNATURE` | `@interrupt` handler has invalid signature |
| `E_INTERRUPT_BLOCKING` | `@interrupt` handler calls blocking code |
| `E_INTERRUPT_STORAGE` | `@interrupt` handler uses persistent storage |
| `E_TASK_SIGNATURE` | `@task` entry point has invalid signature |
| `E_TASK_STACK_REQUIRED` | `@task` requires an explicit stack budget |
| `E_TASK_INTERRUPT_CONFLICT` | function cannot be both `@task` and `@interrupt` |
| `E_STRICT_BLOCKING` | `#[strict]` module calls blocking code |
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
├── io/io.bs
├── mem/mem.bs
├── math/math.bs
├── string/string.bs
├── time/time.bs
├── mmio/mmio.bs
├── bits/bits.bs
├── crc/crc.bs
└── ring/ring.bs

examples/
├── hello.bs
├── bits_demo.bs
├── crc_demo.bs
├── ring_demo.bs
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
