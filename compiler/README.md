# BASIS v1.0 — Compiler Documentation

> **BASIS**: A pure, deterministic, resource-safe systems language for embedded development.

## Documentation Index

| Document | Description |
|----------|-------------|
| [syntax.md](syntax.md) | Complete language syntax reference |
| [safeguards.md](safeguards.md) | Safety guarantees and compile-time checks |
| [limitations.md](limitations.md) | Known limitations and workarounds |

---

## Quick Start

### Hello World
```basis
#[max_memory(1kb)]

fn main() -> i32 {
    return 0;
}
```

### Compile and Run
```bash
python basis.py build hello.bs --run
```

### Library Mode (for linking with C)
BASIS removes `while` loops entirely, so embedded apps typically use C or a HAL for scheduling:
```bash
python basis.py build --lib sensor.bs motor.bs --emit-c
# Link generated C files with your C main loop
```

### With Standard Library
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

---

## Key Features

### 1. Mandatory Memory Budget
Every BASIS file declares its maximum memory usage:
```basis
#[max_memory(256kb)]   // Arduino Uno
#[max_memory(32kb)]    // STM32F103
#[max_memory(512b)]    // Tiny MCU
```
This enables linking with C code for scheduling/control loops.

### 2. Compile-Time Resource Analysis
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

Memory Budget: 1232/262144 bytes (0.5% used)
[OK] Program fits within declared memory budget
```

### 3. Static Safety Checks
- **Array bounds** - Checked at compile time
- **Recursion depth** - Must be annotated with `@recursion(max=N)`
- **Call-graph stack** - Deepest reachable stack is computed across function calls
- **Loop termination** - `while` loops are rejected; only bounded `for` loops remain
- **Heap allocation** - Sizes must be compile-time constants
- **Extern contracts** - `extern fn` declarations must provide `@stack(N)`
- **ISR validation** - `@interrupt` handlers must be deterministic, heap-free, and ISR-safe

### 4. Standard Library
```
stdlib/
├── core/    # abs, min, max, clamp
├── mem/     # alloc_bytes, free_bytes, alloc_i32
├── io/      # print, println, out_i32, out_u32
└── math/    # square, cube, power, is_even, sign
```

---

## Compiler Usage

```bash
# Build only
python basis.py build main.bs

# Build and run
python basis.py build main.bs --run

# Show all resources
python basis.py build main.bs --show-resources
```

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
| `E_INTERRUPT_SIGNATURE` | `@interrupt` handler has invalid signature |
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
    // Use buffer...
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
v1.0/
├── compiler/
│   ├── basis.py          # Main compiler driver
│   ├── lexer.py          # Tokenization
│   ├── parser.py         # Recursive descent parser
│   ├── ast_defs.py       # AST node definitions
│   ├── sema.py           # Semantic analysis
│   ├── typecheck.py      # Type checking
│   ├── consteval.py      # Constant evaluation
│   ├── loop_analysis.py  # Loop bound analysis
│   ├── resource_analysis.py  # Resource tracking
│   ├── codegen.py        # Single-file C generation
│   ├── module_codegen.py # Multi-module C generation
│   └── diagnostics.py    # Error reporting
├── stdlib/
│   ├── core/core.bs
│   ├── mem/mem.bs
│   ├── io/io.bs
│   └── math/math.bs
└── examples/
    ├── hello.bs
    └── test_io.bs
```

---

## Appendix: Extern and C ABI Specification

### Extern Declaration Syntax
```
@stack(N) extern fn IDENTIFIER(param_list?) -> type;
@stack(N) extern fn IDENTIFIER(param_list?) -> type = "symbol_name";
param_list ::= param ("," param)*
param ::= IDENTIFIER ":" type
```
- Allowed types: i8, i16, i32, i64, u8, u16, u32, u64, f32, f64, bool, void return; raw pointers to any allowed type; pointers to structs; structs by value only if trivially C-compatible. 
- Forbidden in extern signatures: arrays, slices, function pointers, opaque handles, managed/high-level types. 
- Variadic functions: forbidden.
- `@stack(N)` is required on every extern so the whole-program call graph stays bounded.

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
- Heap behavior outside compiler unless future annotations (none in v1.0).

### Header Emission Rules
- Headers generated only for non-entry modules; entry (main) emits no header.
- Public externs appear in headers as non-static prototypes; private externs only in .c as static prototypes.
- Headers contain declarations only, never bodies. Own guard first, then standard includes, then imported module headers in lexicographic order.

### Symbol Visibility
- `public fn` → prototype in header, definition in .c (non-static).
- `private fn` → no header prototype; definition in .c as static.
- `extern fn` → prototype only; no definition. Public externs non-static in header; private externs static in .c. Entry `main` is never extern/static and no header is emitted for it.

### Diagnostics
- `E_EXTERN_TYPE`: invalid extern type in signature.
- `E_EXTERN_ALIAS`: invalid extern alias; expected string literal.
- `E_EXTERN_VARIADIC`: variadic externs are not supported.
- `E_EXTERN_STRUCTRET`: struct return not supported by target ABI.
- `E_EXTERN_BODY`: extern functions must not have bodies.

## PART B — Compiler Responsibilities
- Store extern declarations (with optional alias) in symbol table.
- Type check externs like declared functions without bodies; validate parameter/return types.
- Exclude extern bodies from resource/loop analyses; analyze call sites only.
- Externs do not create module import dependencies.
- Emit C prototypes respecting visibility and aliasing; no bodies generated.

## PART C — Code Generation Rules
- Lowering: `extern fn foo(a: i32) -> i32;` → `int32_t foo(int32_t a);`
- Aliasing: `extern fn local(a: i32) -> i32 = "c_symbol";` → `int32_t local(int32_t a) __asm__("c_symbol");` (or equivalent alias mechanism; if unavailable, emit prototype named `c_symbol`).
- Struct pointer extern: `extern fn process(s: *MyStruct) -> i32;` → `int32_t process(struct MyStruct* s);`
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
- Public externs → prototypes in headers; private externs → static prototypes in .c.
- No code emitted for extern bodies; zero-overhead direct calls.
- ABI-compatible prototypes generated with correct C types and calling convention.
- Diagnostics enforced: E_EXTERN_TYPE, E_EXTERN_ALIAS, E_EXTERN_VARIADIC, E_EXTERN_STRUCTRET, E_EXTERN_BODY.
