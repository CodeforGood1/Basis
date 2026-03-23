# Learn BASIS

This guide is for people who are new to BASIS and want to understand the language from the top down before reading the full compiler reference.

## What BASIS Is

BASIS is a deterministic, resource-aware systems programming language for embedded development. It compiles to C and is designed to make important firmware properties visible earlier through compile-time checks and resource analysis.

The language is especially focused on:

- bounded control flow
- explicit memory budgeting
- whole-program stack analysis
- interrupt-safe code
- explicit foreign-function contracts
- integration with existing C-based firmware stacks

## Your First Program

Every BASIS file starts with a memory budget:

```basis
#[max_memory(8kb)]

import io::*;

fn main() -> i32 {
    print("Hello from BASIS\n");
    return 0;
}
```

Run it from the repository root:

```powershell
python compiler\basis.py build examples\hello.bs --run
```

## Core Ideas

### 1. Modules and Imports

Each `.bs` file is a module. Public symbols can be imported from other modules:

```basis
import core::*;
import math::{square_i32};
```

### 2. Explicit Resource Budgets

Every BASIS module declares a maximum memory budget:

```basis
#[max_memory(32kb)]
```

Optional directives can add tighter constraints for embedded use:

```basis
#[strict]
#[max_storage(1kb)]
#[max_storage_objects(8)]
#[max_task_stack(2kb)]
```

### 3. Bounded Control Flow

BASIS removes `while` loops completely. The language only supports bounded `for` loops and bounded recursion.

```basis
for i in 0..8 {
    total = total + values[i];
}

@recursion(max=8)
fn factorial(n: i32) -> i32 {
    if n <= 1 {
        return 1;
    }
    return n * factorial(n - 1);
}
```

### 4. Static Analysis

The compiler reports stack usage, heap usage, task stack, storage usage, code-size estimates, and the deepest call path it found.

That makes BASIS useful for embedded logic where hidden growth is often harder to debug than syntax errors.

## Types You Will Use Most

- integers: `i8`, `i16`, `i32`, `i64`, `u8`, `u16`, `u32`, `u64`
- floating point: `f32`, `f64`
- `bool`
- pointers: `*u8`, `*i32`, `*MyStruct`
- MMIO pointers: `volatile *u32`
- fixed arrays: `[u8; 64]`
- structs

Example:

```basis
struct Sample {
    id: u32,
    value: i32,
}
```

## Foreign Calls and Effects

BASIS can call C functions through `extern fn`, but the compiler requires their behavior to be declared explicitly.

```basis
@deterministic
@blocking
@stack(64)
extern fn print_str(s: *u8) -> void;
```

Useful effect annotations include:

- `@deterministic`
- `@nondeterministic`
- `@blocking`
- `@allocates(max=N)`
- `@storage(max_bytes=N, max_objects=N)`
- `@isr_safe`
- `@reentrant`
- `@uses_timer`
- `@may_fail`

These contracts let BASIS reason about foreign calls instead of treating them as opaque black boxes.

## Tasks and Interrupts

Task entry points and interrupt handlers are first-class parts of the language model.

Task example:

```basis
@task(stack=1024, priority=2)
public fn telemetry_task() -> void {
    return;
}
```

Interrupt example:

```basis
@interrupt
public fn systick_handler() -> void {
    return;
}
```

Interrupt code is restricted to deterministic, non-blocking, non-allocating, storage-free, ISR-safe call paths.

## Standard Library Modules

The current standard library is small and practical. The most useful modules are:

- `core` for basics like `abs`, `min`, `max`, `clamp`, and assertions
- `io` for printing and simple input
- `mem` for explicit heap operations
- `math` for integer math helpers
- `string` for C-style string helpers
- `time` for rollover-safe tick and deadline helpers
- `mmio` for volatile register access
- `bits` for masks, flags, and packed register helpers
- `crc` for fixed-size checksum and CRC helpers
- `ring` for fixed-size byte ring buffers

## Which Libraries Fit BASIS Best Right Now

The most natural libraries for BASIS today are libraries that benefit from bounded control flow, fixed memory shapes, and explicit resource contracts.

Good fits include:

- register and flag manipulation
- packet checksums and framing helpers
- fixed-size queues and ring buffers
- time and deadline helpers
- deterministic control logic
- small protocol helpers

Less natural fits today are large dynamic data structures, generic collections, and abstraction-heavy frameworks. Those are better left for future language work.

## Good Example Programs To Read

- [examples/hello.bs](examples/hello.bs)
- [examples/callgraph_demo.bs](examples/callgraph_demo.bs)
- [examples/effects_demo.bs](examples/effects_demo.bs)
- [examples/time_demo.bs](examples/time_demo.bs)
- [examples/task_demo.bs](examples/task_demo.bs)
- [examples/storage_demo.bs](examples/storage_demo.bs)
- [examples/mmio_demo.bs](examples/mmio_demo.bs)
- [examples/bits_demo.bs](examples/bits_demo.bs)
- [examples/crc_demo.bs](examples/crc_demo.bs)
- [examples/ring_demo.bs](examples/ring_demo.bs)

## Recommended Learning Path

1. Run `examples\hello.bs`
2. Read `examples\callgraph_demo.bs` and inspect `--show-resources`
3. Read `examples\effects_demo.bs` to see foreign contracts
4. Read `examples\time_demo.bs`, `examples\task_demo.bs`, and `examples\isr_demo.bs`
5. Read the library examples for `bits`, `crc`, and `ring`
6. Move to [compiler/syntax.md](compiler/syntax.md) for the full reference

## Useful Commands

Run a program:

```powershell
python compiler\basis.py build examples\hello.bs --run
```

Show resource analysis:

```powershell
python compiler\basis.py build examples\callgraph_demo.bs --show-resources --run
```

Emit C for embedded integration:

```powershell
python compiler\basis.py build examples\mmio_demo.bs --emit-c --target esp32
```

Run the full local verification pipeline:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_local_checks.ps1 -VerifyPackage
```

## Where To Go Next

- [README.md](README.md) for project overview and installation
- [compiler/syntax.md](compiler/syntax.md) for language syntax
- [compiler/safeguards.md](compiler/safeguards.md) for safety checks
- [compiler/limitations.md](compiler/limitations.md) for current limitations
