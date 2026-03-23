# BASIS v1.0 — Syntax Reference

> A pure, deterministic, resource-safe systems language for embedded development.

## Module Structure

Every BASIS source file is a module. The general structure is:

```basis
#[max_memory(SIZE)]     // Required in ALL BASIS files

import module::*;       // Import declarations
import module::{item};  // Named imports

// Declarations: const, fn, struct
```

---

## Memory Directive (Required)

The `#[max_memory(SIZE)]` directive declares the maximum memory budget. **Required** in every BASIS file to enable linking with C code for scheduling and control.

### Why Every File?

BASIS cannot express infinite loops, so embedded applications typically use C for scheduling/control with BASIS functions for deterministic tasks. Each BASIS module declares its memory budget so the C linker can account for total system resources.

### Syntax
```basis
#[max_memory(SIZE)]
```

### Size Formats
| Format | Example | Bytes |
|--------|---------|-------|
| Kilobytes | `256kb` | 262,144 |
| Megabytes | `1mb` | 1,048,576 |
| Bytes (suffix) | `1024b` | 1,024 |
| Raw bytes | `32768` | 32,768 |

### Examples
```basis
#[max_memory(256kb)]    // Arduino Uno - 256KB
#[max_memory(32kb)]     // STM32F103 - 32KB
#[max_memory(1mb)]      // Larger embedded systems
#[max_memory(512b)]     // Tiny microcontrollers
```

---

## Imports

### Wildcard Import
```basis
import core::*;         // Import all public symbols from core
```

### Named Import
```basis
import math::{abs_i32, max_i32};  // Import specific symbols
```

### Standard Library Modules
- `core` — Fundamental operations (abs, min, max, clamp)
- `mem` — Heap allocation (alloc_bytes, free_bytes, alloc_i32)
- `io` — Basic output (print, println, out_i32, out_u32)
- `math` — Advanced math (square, cube, power, is_even, sign)

---

## Types

### Primitive Types
| Type | Description | Size |
|------|-------------|------|
| `i8`, `i16`, `i32`, `i64` | Signed integers | 1, 2, 4, 8 bytes |
| `u8`, `u16`, `u32`, `u64` | Unsigned integers | 1, 2, 4, 8 bytes |
| `f32`, `f64` | Floating point | 4, 8 bytes |
| `bool` | Boolean | 1 byte |
| `void` | No value (return only) | 0 bytes |

### Pointer Types
```basis
*i32        // Pointer to i32
*u8         // Pointer to byte
*MyStruct   // Pointer to struct
```

### Array Types
```basis
[i32; 10]   // Fixed-size array of 10 i32s
[u8; 256]   // Fixed-size array of 256 bytes
```

---

## Declarations

### Constants
```basis
const MAX_SIZE: i32 = 1024;
const PI: f64 = 3.14159;
```

### Variables
```basis
let x: i32 = 42;
let counter: i32 = 0;   // All variables are mutable
```

### Functions
```basis
fn add(a: i32, b: i32) -> i32 {
    return a + b;
}

public fn api_function() -> void {
    // Visible to other modules
}

private fn internal() -> i32 {
    // Module-private (default)
    return 0;
}
```

**Note:** Functions cannot return arrays by value. Use pointers or wrap in a struct:
```basis
// Invalid: fn get_data() -> [u8; 32] { ... }

// Valid alternatives:
struct DataBuffer { data: [u8; 32], }
fn get_data() -> DataBuffer { ... }         // Return struct
fn fill_data(out: *u8) -> void { ... }      // Use out parameter
```

### Extern Functions (C Interop)
```basis
@stack(64) extern fn malloc(size: u32) -> *u8;
@stack(64) extern fn free(ptr: *u8) -> void;
@stack(64) extern fn printf(fmt: *u8) -> i32 = "printf";  // With alias
```

Every `extern fn` must declare `@stack(N)` so the compiler can include foreign calls in the whole-program stack graph.

### Structs
```basis
struct Point {
    x: i32,
    y: i32,
}
```

---

## Expressions

### Literals
```basis
// Decimal integers
42          // i32 integer
1_000_000   // Underscores for readability

// Hexadecimal (0x prefix)
0xFF        // 255
0x1A2B      // 6699
0xFF_FF     // 65535 (with underscores)

// Binary (0b prefix)
0b1010      // 10
0b1111_0000 // 240 (with underscores)

// Float
3.14        // f64 float

// Boolean
true        // bool
false       // bool

// String
"hello"     // string literal (*u8)
```

### Operators

**Arithmetic:** `+`, `-`, `*`, `/`, `%`

**Comparison:** `==`, `!=`, `<`, `>`, `<=`, `>=`

**Logical:** `&&`, `||`, `!`

**Bitwise:** `&`, `|`, `^`, `~`, `<<`, `>>`

### Type Casting
```basis
let x: i32 = 256;
let y: u32 = x as u32;      // Cast i32 to u32
let ptr: *i32 = raw as *i32; // Cast to pointer
```

### Array Literals and Initialization
```basis
// List syntax
let arr: [i32; 5] = [1, 2, 3, 4, 5];

// Repeat syntax: [value; count]
let zeros: [i32; 100] = [0; 100];           // 100 zeros
let filled: [u8; 32] = [0xFF as u8; 32];    // 32 bytes of 0xFF

// Sparse initialization: [default; count; idx: val, ...]
let sparse: [i32; 10] = [0; 10; 1: 10, 5: 50, 9: 99];
// Creates: [0, 10, 0, 0, 0, 50, 0, 0, 0, 99]
```

### Array Access
```basis
let first: i32 = arr[0];    // Bounds-checked at compile time
arr[2] = 42;                // Variable indices checked at runtime
```

### Function Calls
```basis
let result: i32 = add(10, 20);
out_i32(result);
```

---

## Statements

### Assignment
```basis
x = 10;
arr[0] = 42;
```

### If/Else
```basis
if condition {
    // then block
} elif other_condition {
    // elif block  
} else {
    // else block
}
```

### Loops

**For Loop (bounded):**
```basis
for i in 0..10 {
    // Executes 10 times (0 to 9)
}

for i in start..end {
    // Range must be compile-time determinable
}
```

**While Loop:**
```basis
// Not supported.
// Replace with a bounded for loop or recursion with @recursion(max=N).
```

### Return
```basis
fn example() -> i32 {
    return 42;
}
```

---

## Annotations

### Recursion Annotation
```basis
@recursion(max=10)
fn factorial(n: i32) -> i32 {
    if n <= 1 {
        return 1;
    }
    return n * factorial(n - 1);
}
```

### Stack Annotation
```basis
@stack(64) extern fn board_crc(seed: u32) -> u32;
```

`@stack(N)` is required on `extern fn` declarations and can also be used as a budget on normal functions.

### Interrupt Annotation
```basis
@interrupt
public fn systick_handler() -> void {
    return;
}
```

`@interrupt` handlers must be `public`, take no parameters, return `void`, allocate no heap, and only call deterministic ISR-safe code.

---

## Complete Example

```basis
#[max_memory(256kb)]

import core::*;
import io::*;

const ARRAY_SIZE: i32 = 5;

fn sum_array(arr: [i32; 5]) -> i32 {
    let total: i32 = 0;
    for i in 0..5 {
        total = total + arr[i];
    }
    return total;
}

fn main() -> i32 {
    let numbers: [i32; 5] = [10, 20, 30, 40, 50];
    let sum: i32 = sum_array(numbers);
    
    print("Sum: ");
    out_i32(sum);
    println("");
    
    return 0;
}
```

---

## Grammar Summary (EBNF)

```ebnf
module      ::= directive? import* declaration*
directive   ::= "#[" IDENT "(" value ")" "]"
import      ::= "import" path "::" ("*" | "{" ident_list "}")
declaration ::= const_decl | fn_decl | struct_decl | extern_decl
fn_decl     ::= visibility? "fn" IDENT "(" params? ")" "->" type block
const_decl  ::= "const" IDENT ":" type "=" expr ";"
struct_decl ::= "struct" IDENT "{" field_list "}"
extern_decl ::= "extern" "fn" IDENT "(" params? ")" "->" type ("=" STRING)? ";"
```
