# BASIS v1.0 - Safety Guarantees & Safeguards

> How BASIS enforces determinism and bounded resource use at compile time.

## Core Philosophy

BASIS is designed for embedded systems where:
- memory is scarce
- runtime failures are expensive
- predictable execution matters more than expressive freedom
- foreign-function boundaries must be made explicit

The compiler is intentionally opinionated: it would rather reject code early
than let uncertainty survive into firmware.

---

## Resource Budgets

Every BASIS file must declare:

```basis
#[max_memory(256kb)]
```

Optional module profiles can also declare:

```basis
#[strict]
#[max_storage(4kb)]
#[max_storage_objects(16)]
#[max_task_stack(8kb)]
```

### What Gets Counted

| Component | Description |
|-----------|-------------|
| `Stack` | Deepest reachable call-path stack usage |
| `Heap` | Bounded dynamic allocation tracked through calls and loops |
| `Task stack` | Sum of all `@task(stack=N)` reservations |
| `Storage use` | Persistent bytes and object counts from `@storage(...)` |
| `Code (~)` | Estimated generated code size |

### Example Output

```
======================================================================
RESOURCE ANALYSIS
======================================================================

Program Size Summary:
  Stack (max):         68 bytes
  Heap (total):         0 bytes
  Task stack:        1024 bytes
  Storage use:        512 bytes / 4 objects
  Code (~):           300 bytes
  -------------------------------
  TOTAL:             1392 bytes (1.36 KB)
  Deepest path:  main -> persist_batch -> append_log
======================================================================
```

If a program exceeds `#[max_memory(...)]`, `#[max_storage(...)]`,
`#[max_storage_objects(...)]`, or `#[max_task_stack(...)]`, compilation fails.

---

## Deterministic Control Flow

- `while` loops are rejected outright with `E_WHILE_REMOVED`
- `for` loops must have provable bounds
- recursion is allowed only with `@recursion(max=N)`
- recursive cycles must agree on the same recursion depth

This keeps termination and stack growth analyzable.

---

## Heap Safety

- heap allocation sizes must be compile-time constants or bounded parameters
- heap usage is multiplied across bounded loops
- recursive functions cannot allocate heap memory
- generic foreign allocators must declare `@allocates(max=N)`

Example:

```basis
@deterministic @allocates(max=96) @stack(48) extern fn reserve_dma() -> *u8;
```

---

## Persistent Storage Budgeting

Persistent storage is tracked separately from heap because long-running systems
often fail from log growth, object creation, or other state accumulation that
is not ordinary RAM allocation.

Use:

```basis
#[max_storage(4kb)]
#[max_storage_objects(16)]

@deterministic
@storage(max_bytes=128, max_objects=1)
@stack(64)
extern fn append_log(record_id: u32) -> void;
```

The compiler propagates storage use through the whole-program call graph and
multiplies it through bounded loops.

Interrupt handlers and strict modules cannot use persistent storage.

---

## Foreign-Function Effect Contracts

Every `extern fn` must declare:
- `@stack(N)`
- exactly one of `@deterministic` or `@nondeterministic`

Optional refinements:
- `@blocking`
- `@allocates(max=N)`
- `@storage(max_bytes=N, max_objects=N)`
- `@reentrant`
- `@uses_timer`
- `@may_fail`
- `@isr_safe`

Example:

```basis
@deterministic @reentrant @isr_safe @stack(32) extern fn board_crc(seed: u32) -> u32;
@nondeterministic @blocking @stack(64) extern fn read_i32() -> i32;
@deterministic @storage(max_bytes=128, max_objects=1) @stack(64) extern fn append_log(id: u32) -> void;
```

These effects propagate through the same call graph used for stack analysis.

---

## Interrupt Safety

`@interrupt` functions must:
- be `public`
- return `void`
- take no parameters
- not be `extern`
- not be recursive
- not allocate heap
- not use persistent storage
- call only deterministic, ISR-safe, reentrant code
- not call blocking code

Violations surface as errors such as:
- `E_INTERRUPT_SIGNATURE`
- `E_INTERRUPT_HEAP`
- `E_INTERRUPT_STORAGE`
- `E_INTERRUPT_BLOCKING`
- `E_INTERRUPT_NONDETERMINISTIC`
- `E_INTERRUPT_UNSAFE_CALL`
- `E_INTERRUPT_REENTRANCY`

---

## Task Entry Points

`@task(stack=N, priority=M)` marks a function as a runtime task entry point.

Compile-time checks enforce that task functions:
- are `public`
- return `void`
- take no parameters
- are not recursive
- declare an explicit stack budget
- are not also marked `@interrupt`

Task stacks are tracked separately and can be bounded with `#[max_task_stack(...)]`.

---

## Strict Modules

`#[strict]` defines a tighter deterministic profile for a module.

Strict modules reject:
- nondeterministic calls
- blocking calls
- heap allocation
- persistent storage usage

This is useful for control logic that needs a harder guarantee boundary than
the default BASIS profile.

---

## Time and MMIO Support

The standard library now includes:
- `time` for rollover-safe tick/deadline helpers
- `mmio` for typed `volatile` register access helpers

Example:

```basis
import time::*;

let deadline: u32 = deadline_from_u32(0xFFFF_FFF0 as u32, 32 as u32);
let reached: bool = deadline_reached_u32(0x0000_0008 as u32, deadline);
```

```basis
import mmio::*;

let gpio_out: volatile *u32 = 0x3FF44004 as volatile *u32;
write32(gpio_out, 1 as u32);
```

---

## Type Safety

- explicit type annotations on variables
- compile-time type checking for expressions and returns
- no array returns by value
- explicit casts for representation changes
- compile-time and runtime array bounds enforcement where applicable

---

## Summary

BASIS is not trying to be a fully unrestricted systems language. Its safety
model comes from restricting the language until stack usage, heap usage,
persistent storage, interrupts, tasks, and foreign-call behavior are all more
visible at compile time.
