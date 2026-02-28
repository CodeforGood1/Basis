# BASIS String Library

Functions for working with null-terminated strings (`*u8`).

## Import

```basis
import string::*;
```

## Functions

### String Length

| Function | Signature | Description |
|----------|-----------|-------------|
| `len` | `(s: *u8) -> i32` | Get length of string (excluding null terminator) |
| `length` | `(s: *u8) -> i32` | Alias for `len` |

### String Comparison

| Function | Signature | Description |
|----------|-----------|-------------|
| `str_cmp` | `(s1: *u8, s2: *u8) -> i32` | Compare strings: 0 if equal, <0 if s1<s2, >0 if s1>s2 |
| `str_eq` | `(s1: *u8, s2: *u8) -> bool` | Check if two strings are equal |
| `str_cmp_n` | `(s1: *u8, s2: *u8, n: i32) -> i32` | Compare first n characters |
| `str_starts_with` | `(s: *u8, prefix: *u8) -> bool` | Check if string starts with prefix |

### String Copy

| Function | Signature | Description |
|----------|-----------|-------------|
| `str_copy` | `(dest: *u8, src: *u8) -> void` | Copy string (dest must be large enough) |
| `str_copy_n` | `(dest: *u8, src: *u8, n: i32) -> void` | Copy at most n characters |

### String Concatenation

| Function | Signature | Description |
|----------|-----------|-------------|
| `str_append` | `(dest: *u8, src: *u8) -> void` | Append src to dest (dest must have space) |

### Character Search

| Function | Signature | Description |
|----------|-----------|-------------|
| `str_find_char` | `(s: *u8, c: u8) -> *u8` | Find first occurrence of character |

### Character Classification (ASCII)

| Function | Signature | Description |
|----------|-----------|-------------|
| `is_digit` | `(c: u8) -> bool` | Check if character is 0-9 |
| `is_upper` | `(c: u8) -> bool` | Check if character is A-Z |
| `is_lower` | `(c: u8) -> bool` | Check if character is a-z |
| `is_alpha` | `(c: u8) -> bool` | Check if character is a letter |
| `is_alnum` | `(c: u8) -> bool` | Check if character is letter or digit |
| `is_space` | `(c: u8) -> bool` | Check if character is whitespace |

### Character Conversion

| Function | Signature | Description |
|----------|-----------|-------------|
| `to_lower` | `(c: u8) -> u8` | Convert uppercase to lowercase |
| `to_upper` | `(c: u8) -> u8` | Convert lowercase to uppercase |

## Example

```basis
#[max_memory(4kb)]
import io::*;
import string::*;

fn main() -> i32 {
    let msg: *u8 = "Hello, World!";
    
    out_str("Length: ");
    out_i32(len(msg));
    out_ln();
    
    if str_starts_with(msg, "Hello") {
        println("Starts with Hello!");
    }
    
    if str_eq(msg, "Hello, World!") {
        println("Strings are equal!");
    }
    
    return 0;
}
```

## Safety Notes

- String copy/append functions do NOT check buffer bounds
- Caller must ensure destination buffers are large enough
- All strings must be null-terminated
