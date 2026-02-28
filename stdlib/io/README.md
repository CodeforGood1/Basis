# BASIS Standard Library - IO

## String Output

| Function | Description |
|----------|-------------|
| `print(s: *u8)` | Print string without newline |
| `println(s: *u8)` | Print string with newline |
| `newline()` | Print newline only |

## Integer Output (no newline)

| Function | Description |
|----------|-------------|
| `out_i8(x: i8)` | Print signed 8-bit integer |
| `out_i16(x: i16)` | Print signed 16-bit integer |
| `out_i32(x: i32)` | Print signed 32-bit integer |
| `out_i64(x: i64)` | Print signed 64-bit integer |
| `out_u8(x: u8)` | Print unsigned 8-bit integer |
| `out_u16(x: u16)` | Print unsigned 16-bit integer |
| `out_u32(x: u32)` | Print unsigned 32-bit integer |
| `out_u64(x: u64)` | Print unsigned 64-bit integer |

## Floating Point Output (no newline)

| Function | Description |
|----------|-------------|
| `out_f32(x: f32)` | Print 32-bit float |
| `out_f64(x: f64)` | Print 64-bit float |

## Other Output (no newline)

| Function | Description |
|----------|-------------|
| `out_bool(x: bool)` | Print "true" or "false" |
| `out_char(c: u8)` | Print single character |
| `out_ptr(p: *u8)` | Print pointer address |

## Mixed Output Helpers

For printing multiple values on the same line, use `sp_*` functions (print value + space):

| Function | Description |
|----------|-------------|
| `space()` | Print single space |
| `sp_str(s: *u8)` | Print string + space |
| `sp_i32(x: i32)` | Print i32 + space |
| `sp_u32(x: u32)` | Print u32 + space |
| `sp_i64(x: i64)` | Print i64 + space |
| `sp_u64(x: u64)` | Print u64 + space |
| `sp_f32(x: f32)` | Print f32 + space |
| `sp_f64(x: f64)` | Print f64 + space |
| `sp_bool(x: bool)` | Print bool + space |

## Input Functions

| Function | Description |
|----------|-------------|
| `in_i32()` | Read signed 32-bit integer from stdin |
| `in_i64()` | Read signed 64-bit integer from stdin |
| `in_u32()` | Read unsigned 32-bit integer from stdin |
| `in_u64()` | Read unsigned 64-bit integer from stdin |
| `in_f32()` | Read 32-bit float from stdin |
| `in_f64()` | Read 64-bit float from stdin |
| `in_char()` | Read single character from stdin |
| `in_line(buf, max_len)` | Read line into buffer (strips newline) |

## Prompted Input

| Function | Description |
|----------|-------------|
| `prompt_i32(msg)` | Print message, then read i32 |
| `prompt_i64(msg)` | Print message, then read i64 |
| `prompt_f64(msg)` | Print message, then read f64 |
| `prompt_line(msg, buf, max_len)` | Print message, then read line |

## Example

```basis
#[max_memory(4kb)]
import io::*;

fn main() -> i32 {
    // Basic output
    println("Hello, BASIS!");

    // Print values
    print("Value: ");
    out_i32(42);
    newline();

    // Mixed output on same line
    print("Result: ");
    sp_str("x=");
    sp_i32(10);
    sp_str("y=");
    sp_f64(3.14);
    sp_str("ok=");
    out_bool(true);
    newline();
    // Output: Result: x= 10 y= 3.14 ok= true

    return 0;
}
```

## Design Notes

- Thin C ABI bindings only
- No allocation or formatting abstractions  
- No variadic functions (type-safe wrappers)
- No heap usage or hidden behavior
- The `out_*` naming convention is used for the public API to avoid symbol conflicts with compiler-provided C runtime helpers
