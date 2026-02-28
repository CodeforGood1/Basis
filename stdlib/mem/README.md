# BASIS Memory Library

Explicit heap allocation utilities for BASIS v1.0.

## API Reference

| Function | Description |
|----------|-------------|
| `alloc_bytes(size: u32) -> *u8` | Allocate raw bytes |
| `alloc_zeroed(size: u32) -> *u8` | Allocate zero-initialized bytes |
| `free_bytes(ptr: *u8) -> void` | Free allocated memory |
| `alloc_u8(count: u32) -> *u8` | Allocate u8 array |
| `alloc_i32(count: u32) -> *i32` | Allocate i32 array |
| `alloc_u32(count: u32) -> *u32` | Allocate u32 array |
| `alloc_i64(count: u32) -> *i64` | Allocate i64 array |
| `mem_copy(dest: *u8, src: *u8, size: u32) -> void` | Copy memory region |
| `mem_zero(ptr: *u8, size: u32) -> void` | Zero out memory region |
| `mem_set(ptr: *u8, value: u8, size: u32) -> void` | Fill memory with byte value |

## Design

- Explicit heap allocation only (malloc/free externs)
- No hidden allocation or safety layers
- No runtime metadata or runtime checks
- Compatible with compile-time resource analyzer
