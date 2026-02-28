# BASIS Core Library

Core utility functions - pure BASIS code with no external dependencies.

## Import

```basis
import core::*;
```

## Functions

### Absolute Value

| Function | Signature | Description |
|----------|-----------|-------------|
| `abs` | `(x: i32) -> i32` | Absolute value (convenience alias) |
| `abs_i32` | `(x: i32) -> i32` | Absolute value for i32 |
| `abs_i64` | `(x: i64) -> i64` | Absolute value for i64 |

### Min/Max

| Function | Signature | Description |
|----------|-----------|-------------|
| `min` | `(a: i32, b: i32) -> i32` | Minimum (convenience alias) |
| `max` | `(a: i32, b: i32) -> i32` | Maximum (convenience alias) |
| `min_i32` | `(a: i32, b: i32) -> i32` | Minimum of two i32 values |
| `max_i32` | `(a: i32, b: i32) -> i32` | Maximum of two i32 values |
| `min_u32` | `(a: u32, b: u32) -> u32` | Minimum of two u32 values |
| `max_u32` | `(a: u32, b: u32) -> u32` | Maximum of two u32 values |
| `min_i64` | `(a: i64, b: i64) -> i64` | Minimum of two i64 values |
| `max_i64` | `(a: i64, b: i64) -> i64` | Maximum of two i64 values |
| `min_u64` | `(a: u64, b: u64) -> u64` | Minimum of two u64 values |
| `max_u64` | `(a: u64, b: u64) -> u64` | Maximum of two u64 values |

### Clamp

| Function | Signature | Description |
|----------|-----------|-------------|
| `clamp` | `(val: i32, min: i32, max: i32) -> i32` | Clamp value (alias) |
| `clamp_i32` | `(val: i32, min: i32, max: i32) -> i32` | Clamp i32 to range |
| `clamp_u32` | `(val: u32, min: u32, max: u32) -> u32` | Clamp u32 to range |

### Sign

| Function | Signature | Description |
|----------|-----------|-------------|
| `sign` | `(x: i32) -> i32` | Returns -1, 0, or 1 (alias) |
| `sign_i32` | `(x: i32) -> i32` | Sign of i32: -1, 0, or 1 |

### Swap

| Function | Signature | Description |
|----------|-----------|-------------|
| `swap_i32` | `(a: *i32, b: *i32) -> void` | Swap two i32 values via pointers |
| `swap_u32` | `(a: *u32, b: *u32) -> void` | Swap two u32 values via pointers |

### Boolean Operations

| Function | Signature | Description |
|----------|-----------|-------------|
| `bool_not` | `(x: bool) -> bool` | Logical NOT |
| `bool_and` | `(a: bool, b: bool) -> bool` | Logical AND |
| `bool_or` | `(a: bool, b: bool) -> bool` | Logical OR |

### Assertions

| Function | Signature | Description |
|----------|-----------|-------------|
| `assert` | `(cond: bool) -> void` | Assert condition (currently no-op) |

## Example

```basis
#[max_memory(4kb)]
import core::*;
import io::*;

fn main() -> i32 {
    let a: i32 = -5;
    let b: i32 = 10;
    
    out_str("abs(-5) = ");
    out_i32(abs(a));
    out_ln();
    
    out_str("max(-5, 10) = ");
    out_i32(max(a, b));
    out_ln();
    
    out_str("clamp(15, 0, 10) = ");
    out_i32(clamp(15, 0, 10));
    out_ln();
    
    return 0;
}
```

## Design

- Pure BASIS code - no extern calls
- No heap allocation or IO
- Deterministic and total
- No platform dependencies
