# BASIS Stdlib IO (Phase 3)

Public APIs
- print(s: *u8) -> void
- println(s: *u8) -> void
- print_i32(x: i32) -> void
- print_u32(x: u32) -> void

Externs
- extern fn printf(fmt: *u8) -> i32;
- extern fn puts(s: *u8) -> i32;

Rules
- Thin C ABI only
- No allocation or formatting abstractions
- No safety layers or variadic exposure
- No heap usage or hidden behavior
