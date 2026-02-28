# BASIS Math Library

Pure mathematical functions for BASIS v1.0.

## Features

- **No extern functions** — Pure BASIS code only
- **No heap allocation** — Stack-based, deterministic
- **No I/O** — Pure computation
- **Resource-safe** — Passes compile-time resource analysis

## API Reference

### Square & Cube

| Function | Description |
|----------|-------------|
| `square_i32(x: i32) -> i32` | Returns x * x |
| `square_u32(x: u32) -> u32` | Returns x * x (unsigned) |
| `cube_i32(x: i32) -> i32` | Returns x * x * x |
| `cube_u32(x: u32) -> u32` | Returns x * x * x (unsigned) |

### Exponentiation

| Function | Description |
|----------|-------------|
| `power_i32(base: i32, exp: i32) -> i32` | Integer power via repeated squaring |

### Parity

| Function | Description |
|----------|-------------|
| `is_even_i32(x: i32) -> bool` | Returns true if x is even |
| `is_odd_i32(x: i32) -> bool` | Returns true if x is odd |

### Sign

| Function | Description |
|----------|-------------|
| `sign_i32(x: i32) -> i32` | Returns 1, 0, or -1 |
| `is_positive_i32(x: i32) -> bool` | Returns true if x > 0 |
| `is_negative_i32(x: i32) -> bool` | Returns true if x < 0 |

### Number Theory

| Function | Description |
|----------|-------------|
| `gcd(a: i32, b: i32) -> i32` | Greatest common divisor (Euclidean) |
| `div_ceil(n: i32, d: i32) -> i32` | Integer division rounding up |
| `is_power_of_two(x: i32) -> bool` | True if x is a power of 2 |

### Embedded Utilities

| Function | Description |
|----------|-------------|
| `map_range(value, in_min, in_max, out_min, out_max) -> i32` | Linear mapping between ranges |

```basis
// Map ADC reading (0..4095) to temperature (0..100)
let temp: i32 = map_range(adc_value, 0, 4095, 0, 100);
```

## Usage

Build as a library and link at C level:
```bash
python ../../compiler/basis.py build math.bs --emit-c --lib
```

Or include in a project with a main.bs file:
```bash
python ../../compiler/basis.py build main.bs math.bs --emit-c
```

## Notes

- All functions are `public` and can be imported by other modules
- Functions follow BASIS naming conventions (lowercase with underscores)
- Type names follow PascalCase convention (e.g., `Point`, `Vector2D`)
