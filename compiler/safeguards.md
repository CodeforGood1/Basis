# BASIS v1.0 — Safety Guarantees & Safeguards

> How BASIS ensures resource safety and deterministic execution at compile time.

## Core Philosophy

BASIS is designed for **embedded systems** where:
- Memory is scarce and precious
- Runtime failures are catastrophic  
- Predictable execution is mandatory
- Every byte must be accounted for

**All safety checks happen at compile time — zero runtime overhead.**

---

## Memory Budget Enforcement

### The `#[max_memory(SIZE)]` Directive

Every BASIS file must declare its maximum memory budget upfront:

```basis
#[max_memory(256kb)]  // For Arduino Uno (32KB RAM, but 256KB program space)

fn process_sensor() -> i32 {
    // Compiler ensures this module's usage fits within 256KB
    return 0;
}
```

### Why Every File?

BASIS cannot express infinite loops, making it unsuitable for top-level scheduling. Embedded applications typically use C for main loops and scheduling, calling BASIS functions for deterministic tasks. Each BASIS module declares its budget so the C linker can account for total system resources.

### What Gets Counted

| Component | Description | How Measured |
|-----------|-------------|--------------|
| **Stack** | Local variables, function frames | Sum of all local variable sizes × call depth |
| **Heap** | Dynamic allocations | Sum of all `alloc_*` call arguments |
| **Code** | Generated instructions | Estimated from AST complexity |

### Compile-Time Validation

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
======================================================================

Memory Budget: 1232/262144 bytes (0.5% used)
Remaining:     260912 bytes (254.80 KB)
[OK] Program fits within declared memory budget
```

### Budget Violation Detection

If the program exceeds its budget:

```
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
ERROR: Program exceeds declared memory budget!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

  Declared max_memory:      512 bytes (0.50 KB)
  Actual program size:     1232 bytes (1.20 KB)
  Overflow:                 720 bytes

Either reduce program size or increase #[max_memory(SIZE)].
```

---

## Array Bounds Checking

### Compile-Time Bounds Verification

BASIS verifies all array accesses at compile time:

```basis
let arr: [i32; 5] = [1, 2, 3, 4, 5];

let valid: i32 = arr[4];   // OK: index 4 < size 5
let invalid: i32 = arr[10]; // ERROR: index 10 >= size 5
```

**Error:**
```
error: array index 10 is out of bounds for array of size 5 [E_INDEX_OUT_OF_BOUNDS]
```

### Works Across Modules

Bounds checking works even with imported functions:

```basis
import core::*;  // Imports clamp_i32, etc.

let arr: [i32; 5] = [1, 2, 3, 4, 5];
let idx: i32 = clamp_i32(user_input, 0, 4);  // Clamped to valid range
let safe: i32 = arr[idx];  // Compiler knows idx ∈ [0, 4]
```

---

## Recursion Control

### Mandatory Depth Annotation

Recursive functions **must** declare maximum recursion depth:

```basis
@recursion(max=10)
fn factorial(n: i32) -> i32 {
    if n <= 1 {
        return 1;
    }
    return n * factorial(n - 1);
}
```

### Stack Calculation with Recursion

The compiler multiplies stack usage by recursion depth:

```
fn factorial: stack=8 bytes × max_depth=10 = 80 bytes total
```

### Missing Annotation Error

```basis
fn fibonacci(n: i32) -> i32 {
    if n <= 1 { return n; }
    return fibonacci(n - 1) + fibonacci(n - 2);
}
```

**Error:**
```
error: recursive function 'fibonacci' missing @recursion(max=N) annotation 
       (cycle: fibonacci -> fibonacci) [E_MISSING_RECURSION_ANNOTATION]
```

---

## Loop Termination

### Bounded Loops Required

All loops must have provable termination:

```basis
// OK: Bounded for loop
for i in 0..100 {
    process(i);
}

// OK: While with clear termination
let mut count: i32 = 10;
while count > 0 {
    count = count - 1;
}
```

### Unbounded Loop Detection

```basis
// ERROR: Cannot prove termination
while true {
    // infinite loop
}

// ERROR: Loop bound not determinable
for i in 0..runtime_value {
    // Unknown iteration count
}
```

**Error:**
```
error: loop has no determinable upper bound [E_UNBOUNDED_LOOP]
```

---

## Heap Allocation Tracking

### Allocation Size Must Be Known

All heap allocations must have compile-time known sizes:

```basis
import mem::*;

// OK: Constant size
let buf: *u8 = alloc_bytes(256 as u32);

// OK: Compile-time constant
const BUFFER_SIZE: u32 = 1024;
let data: *u8 = alloc_bytes(BUFFER_SIZE);

// ERROR: Runtime-determined size
let dynamic: *u8 = alloc_bytes(user_input);  // Not allowed!
```

### Heap in Loops

Allocations inside loops are multiplied by loop bound:

```basis
for i in 0..10 {
    let ptr: *u8 = alloc_bytes(100 as u32);  // 100 × 10 = 1000 bytes heap
    // ...
    free_bytes(ptr);
}
```

---

## Type Safety

### Explicit Type Annotations

All variables must have explicit types:

```basis
let x: i32 = 42;        // OK
let y = 42;             // ERROR: Type annotation required
```

### Type Mismatch Detection

```basis
fn process(value: u32) -> void { }

let x: i32 = 10;
process(x);  // ERROR: expected u32, got i32
process(x as u32);  // OK: explicit cast
```

### Pointer Type Safety

```basis
let ptr_i32: *i32 = get_data();
let ptr_u8: *u8 = ptr_i32;  // ERROR: pointer type mismatch
let ptr_u8: *u8 = ptr_i32 as *u8;  // OK: explicit cast
```

---

## Missing Directive Detection

### All Modules Require Memory Directive

Every BASIS file must have the memory directive:

```basis
// Missing #[max_memory(SIZE)] directive!

fn process_data(x: i32) -> i32 {
    return x * 2;
}
```

**Error:**
```
error: missing #[max_memory(SIZE)] directive in module(s):
  - my_module

BASIS requires explicit memory budget declaration in EVERY file.
This allows BASIS modules to be linked with C code for scheduling/control.
Add at the top of each file: #[max_memory(SIZE)]  // e.g. #[max_memory(4kb)]
```

### Library Mode

Use `--lib` flag to compile BASIS modules without `main()` for linking with C:

```bash
basis build --lib sensor_driver.bs motor_control.bs --emit-c
```

This generates C files that can be linked with your C scheduler/main loop.

---

## Return Value Checking

### All Paths Must Return

Functions with non-void return types must return a value on **all** code paths:

```basis
fn classify(x: i32) -> i32 {
    if x > 0 {
        return 1;
    }
    // ERROR: missing return when x <= 0
}
```

**Error:**
```
error: function 'classify' must return a value of type i32 on all code paths [E_MISSING_RETURN]
```

### Correct Patterns

```basis
// Pattern 1: Return on all branches
fn classify(x: i32) -> i32 {
    if x > 0 {
        return 1;
    } else {
        return -1;
    }
}

// Pattern 2: Final return catches fall-through
fn classify(x: i32) -> i32 {
    if x > 0 {
        return 1;
    }
    return -1;  // Catches all other cases
}

// Pattern 3: elif chain with final else
fn grade(score: i32) -> i32 {
    if score >= 90 {
        return 5;
    } elif score >= 80 {
        return 4;
    } elif score >= 70 {
        return 3;
    } else {
        return 2;
    }
}
```

---

## Summary of Safety Checks

| Check | When | Error Code |
|-------|------|------------|
| Memory budget | Link time | `Program exceeds declared memory budget` |
| Array bounds | Type check | `E_INDEX_OUT_OF_BOUNDS` |
| Missing return | Type check | `E_MISSING_RETURN` |
| Recursion depth | Semantic analysis | `E_MISSING_RECURSION_ANNOTATION` |
| Loop termination | Semantic analysis | `E_UNBOUNDED_LOOP` |
| Heap size known | Resource analysis | `E_UNBOUNDED_HEAP` |
| Type matching | Type check | `E_TYPE_MISMATCH` |
| Memory directive | Parse/compile | `missing #[max_memory(SIZE)] directive` |

---

## Safety Guarantees

With BASIS, you get **compile-time guarantees** that:

1. **No stack overflow** — Stack usage bounded and known
2. **No heap overflow** — All allocations tracked against budget  
3. **No buffer overflows** — Array bounds checked statically
4. **No infinite loops** — All loops provably terminate
5. **No runaway recursion** — Recursion depth declared and enforced
6. **No type confusion** — Explicit types, explicit casts
7. **No hidden allocations** — All memory usage visible in source
8. **No missing returns** — All code paths return proper values

**If it compiles, it fits in memory.**
