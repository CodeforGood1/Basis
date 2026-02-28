# BASIS v1.0 — Compiler Documentation

> **BASIS**: A pure, deterministic, resource-safe systems language for embedded development.

## Documentation Index

| Document | Description |
|----------|-------------|
| [syntax.md](compiler/syntax.md) | Complete language syntax reference |
| [safeguards.md](compiler/safeguards.md) | Safety guarantees and compile-time checks |
| [limitations.md](compiler/limitations.md) | Known limitations and workarounds |

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

### Emit C Only (No gcc)
```bash
python basis.py build hello.bs --emit-c
```

### Library Mode (for linking with C)
BASIS supports `while` loops for event-driven embedded code, but you can also 
export functions as a C library for integration with existing firmware:
```bash
python basis.py build --lib sensor.bs motor.bs --emit-c
# Link generated C files with your C main loop
```

### Target Validation
```bash
python basis.py build firmware.bs --target stm32f103
# Validates against STM32F103 memory limits (20KB SRAM, 64KB Flash)
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
The compiler verifies total program size (stack + heap + code) fits within the declared budget.

### 2. Compile-Time Resource Analysis
```
======================================================================
RESOURCE ANALYSIS
======================================================================

Program Size Summary:
  Stack (max):         24 bytes
  Heap (total):         0 bytes
  Code (~):          1200 bytes
  -------------------------------
  TOTAL:             1224 bytes (1.20 KB)
======================================================================

Memory Budget: 1224/4096 bytes (29.9% used)
[OK] Program fits within declared memory budget
```

### 3. Static Safety Checks
- **Array bounds** — Checked at compile time for constants, runtime checks for variables
- **Recursion depth** — Must be annotated with `@recursion(max=N)`
- **Loop termination** — For loops are always bounded; while loops emit warnings unless `@bounded(max=N)` 
- **Heap allocation** — Sizes must be compile-time constants
- **Dead code** — Unused private functions generate warnings

### 4. Embedded-Focused Annotations
```basis
@inline                         // Emit as static inline in C
fn fast_op(x: u32) -> u32 { return x << 1; }

@bounded(max=1000)              // Prove while loop terminates
fn process(data: *u8) -> void { ... }

@recursion(max=10)              // Bound recursion depth
fn factorial(n: i32) -> i32 { ... }

@align(4)                       // Struct alignment for DMA/MMIO
struct DmaBuffer { data: [u8; 64], }

@stack(256)                     // Per-function stack budget
fn handler() -> void { ... }
```

### 5. Volatile Types for MMIO
```basis
// Memory-mapped I/O registers
let reg: volatile *u32 = 0x40020000 as volatile *u32;
```

### 6. Bitwise Operations
```basis
fn set_bit(val: u32, bit: u32) -> u32 { return val | ((1 as u32) << bit); }
fn clear_bit(val: u32, bit: u32) -> u32 { return val & (~((1 as u32) << bit)); }
fn test_bit(val: u32, bit: u32) -> bool { return (val & ((1 as u32) << bit)) != (0 as u32); }
```

### 7. While Loops
```basis
fn delay(count: i32) -> void {
    let i: i32 = 0;
    while i < count {
        i = i + 1;
    }
}
```

### 8. Standard Library
```
stdlib/
├── core/    # assert, abs, min, max, clamp, swap, sign, assert_eq/ne/true/false
├── mem/     # alloc_bytes, free_bytes, alloc_u8/u32/i64, alloc_zeroed, mem_copy, mem_zero, mem_set
├── io/      # print, println, out_i32, out_u32, in_i32, prompt_i32, space, newline
├── math/    # square, cube, power, is_even, gcd, div_ceil, is_power_of_two, map_range
└── string/  # len, str_eq, str_copy, str_starts_with, is_digit, is_alpha, to_lower, to_upper
```

### 9. Target Platform Validation
```bash
python basis.py build firmware.bs --target stm32f103
```
Supported targets: `stm32f103`, `stm32f407`, `esp32`, `arduino_uno`, `rpi_pico`, `host`

---

## Compiler Pipeline

```
Source (.bs) → Lexer → Parser → Semantic Analysis → Type Checking
    → Constant Evaluation → Loop Analysis → Resource Analysis → Code Generation (.c/.h)
    → gcc → Executable
```

8-stage pipeline with full static verification before any code is emitted.

---

## Compiler Usage

```bash
# Build and link (requires gcc in PATH)
python basis.py build main.bs

# Build and run
python basis.py build main.bs --run

# Emit C only (no gcc required)
python basis.py build main.bs --emit-c

# Show per-function resource breakdown
python basis.py build main.bs --show-resources

# Build as library (exports all functions)
python basis.py build --lib sensor.bs motor.bs

# Validate against embedded target
python basis.py build main.bs --target stm32f103
```

---

## Safety Errors

| Error | Meaning |
|-------|---------|
| `E_INDEX_OUT_OF_BOUNDS` | Array access exceeds declared size |
| `E_UNBOUNDED_LOOP` | For loop without determinable bound |
| `W_UNBOUNDED_WHILE` | While loop without `@bounded(max=N)` (warning) |
| `E_MISSING_RECURSION_ANNOTATION` | Recursive function needs `@recursion(max=N)` |
| `E_UNBOUNDED_HEAP` | Allocation size not compile-time constant |
| `E_MISSING_RETURN` | Function must return value on all paths |
| `E_INVALID_RETURN_TYPE` | Cannot return arrays by value |
| `missing #[max_memory]` | File lacks memory directive |
| `Program exceeds declared memory budget` | Total usage > declared max |
| `W_UNUSED_FUNCTION` | Private function never called (warning) |

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
    let mut total: i32 = 0;
    for i in 0..5 {
        total = total + arr[i];
    }
    return total;
}
```

### Embedded GPIO (Bitwise + While + @inline)
```basis
#[max_memory(4kb)]

extern fn print_str(s: *u8) -> void;
extern fn print_u32(val: u32) -> void;

@inline
fn set_bit(value: u32, bit: u32) -> u32 {
    return value | ((1 as u32) << bit);
}

@inline
fn clear_bit(value: u32, bit: u32) -> u32 {
    return value & (~((1 as u32) << bit));
}

fn delay(count: i32) -> void {
    let i: i32 = 0;
    while i < count {
        i = i + 1;
    }
}

struct RingBuffer {
    head: u32,
    tail: u32,
    count: u32,
    capacity: u32,
}

fn ring_buffer_init(capacity: u32) -> RingBuffer {
    return RingBuffer { head: 0 as u32, tail: 0 as u32, count: 0 as u32, capacity: capacity };
}

fn main() -> i32 {
    let reg: u32 = 0 as u32;
    reg = set_bit(reg, 5 as u32);
    delay(100);
    return 0;
}
```

---

## Project Structure

```
v1.0/
├── compiler/
│   ├── basis.py            # Main compiler driver (build/run/emit-c)
│   ├── lexer.py            # Tokenization (keywords, operators, literals)
│   ├── parser.py           # Recursive descent parser → AST
│   ├── ast_defs.py         # AST node definitions (dataclasses)
│   ├── sema.py             # Semantic analysis (scoping, dead code)
│   ├── typecheck.py        # Type checking (inference, coercion)
│   ├── consteval.py        # Constant evaluation / folding
│   ├── loop_analysis.py    # Loop bound verification
│   ├── resource_analysis.py # Stack/heap/code size tracking
│   ├── codegen.py          # Single-file C99 code generation
│   ├── module_codegen.py   # Multi-module C generation (.c/.h)
│   ├── target_config.py    # Embedded target definitions
│   └── diagnostics.py      # Error/warning reporting engine
├── stdlib/
│   ├── core/core.bs        # assert, abs, min, max, clamp, swap, sign
│   ├── mem/mem.bs          # alloc, free, mem_copy, mem_zero, mem_set
│   ├── io/io.bs            # print, println, out_*, in_*, prompt_*
│   ├── math/math.bs        # square, cube, power, gcd, div_ceil, map_range
│   └── string/string.bs    # len, str_eq, str_copy, is_digit, to_lower
├── examples/
│   ├── hello.bs            # Minimal hello world
│   ├── core_demo.bs        # Core library demo
│   ├── arrays_demo.bs      # Array operations
│   ├── math_demo.bs        # Math library demo
│   ├── memory_demo.bs      # Heap allocation demo
│   ├── recursion_demo.bs   # Bounded recursion demo
│   ├── embedded_demo.bs    # GPIO, ring buffer, bitwise ops
│   └── test_io.bs          # I/O functionality test
└── build/                   # Generated C output (auto-cleaned)
```

---

## Appendix: Extern and C ABI Specification

### Extern Declaration Syntax
```
extern fn IDENTIFIER(param_list?) -> type;
extern fn IDENTIFIER(param_list?) -> type = "symbol_name";
param_list ::= param ("," param)*
param ::= IDENTIFIER ":" type
```
- Allowed types: i8, i16, i32, i64, u8, u16, u32, u64, f32, f64, bool, void return; raw pointers to any allowed type; pointers to structs; structs by value only if trivially C-compatible. 
- Forbidden in extern signatures: arrays, slices, function pointers, opaque handles, managed/high-level types. 
- Variadic functions: forbidden.

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
