# BASIS v1.0 — Limitations

> Known limitations and design constraints of the BASIS language.

## By Design (Intentional)

These limitations exist to guarantee determinism and resource safety:

### No Dynamic Features
| Feature | Status | Reason |
|---------|--------|--------|
| Dynamic dispatch | Not supported | Unpredictable execution time |
| Virtual functions | Not supported | Runtime overhead, indirection |
| Reflection | Not supported | Runtime type inspection unpredictable |
| Exceptions | Not supported | Hidden control flow, stack unwinding |
| Garbage collection | Not supported | Non-deterministic pauses |

### No Unbounded Operations
| Feature | Status | Reason |
|---------|--------|--------|
| Unbounded recursion | Not supported | Stack overflow risk |
| Unbounded loops | Not supported | Cannot prove termination |
| `while` loops | Not supported | Deterministic control flow is enforced structurally |
| Dynamic arrays | Not supported | Unbounded memory growth |
| Variadic functions | Not supported | Unknown argument count |

### Memory Constraints
| Feature | Status | Reason |
|---------|--------|--------|
| Implicit allocation | Not supported | Hidden memory usage |
| Global mutable state | Restricted | Must be explicit |
| Heap without tracking | Not supported | Must use `alloc_*` functions |

---

## Current Implementation Limitations (v1.0)

These may be addressed in future versions:

### Type System
- **No generics/templates** — Functions must be written for specific types
- **No type inference** — All types must be explicitly annotated
- **No traits/interfaces** — No polymorphism mechanism
- **No enums with data** — Only C-style enums (values only)
- **No tuples** — Use structs instead
- **No Option/Result types** — Use sentinel values or error codes

### Expressions
- **No closures/lambdas** — Functions cannot capture environment
- **No operator overloading** — Operators work only on primitives
- **No method syntax** — Use `func(struct)` not `struct.method()`
- **No string interpolation** — Use print functions separately

### Memory
- **No automatic memory management** — Manual alloc/free required
- **No RAII/destructors** — Resources must be explicitly freed
- **No smart pointers** — Raw pointers only
- **No slice types** — Use pointer + length manually

### Modules
- **No circular imports** - Module dependencies must be acyclic
- **No conditional compilation** - No `#ifdef` equivalent
- **No macros** - No compile-time code generation
- **No `mut` keyword** - All variables are mutable by default

### Arrays
- **Fixed size only** — Size must be compile-time constant
- **No array slicing** — Cannot take subarray views
- **No array return by value** — Functions cannot return arrays; use pointers or wrap in struct
- **Bounds checking** — Compile-time for constants, runtime for variables

### Literals
- **Integer literals default to i32** — Use `as u32` for unsigned

---

## Workarounds

### For Missing Generics
```basis
// Write type-specific functions
fn max_i32(a: i32, b: i32) -> i32 { ... }
fn max_u32(a: u32, b: u32) -> u32 { ... }
fn max_f64(a: f64, b: f64) -> f64 { ... }
```

### For Missing Option Type
```basis
// Use sentinel values
const NONE: i32 = -1;

fn find(arr: [i32; 10], target: i32) -> i32 {
    for i in 0..10 {
        if arr[i] == target {
            return i;
        }
    }
    return NONE;  // Not found
}
```

### For Missing Result Type
```basis
// Use error codes
const OK: i32 = 0;
const ERR_NOT_FOUND: i32 = -1;
const ERR_INVALID: i32 = -2;

fn parse(input: *u8) -> i32 {
    // Return error code or valid result
}
```

### For Dynamic Arrays
```basis
// Pre-allocate maximum size
const MAX_ITEMS: i32 = 100;
let items: [i32; 100];
let count: i32 = 0;  // Track actual usage
```

### For Method Syntax
```basis
// Use free functions with struct as first parameter
struct Point { x: i32, y: i32 }

fn point_add(p: Point, dx: i32, dy: i32) -> Point {
    return Point { x: p.x + dx, y: p.y + dy };
}
```

---

## Platform Limitations

### Integer Sizes
- All integer operations use fixed-width types
- No automatic promotion beyond operation width
- Overflow behavior is defined (wrapping for unsigned, undefined for signed)

### Floating Point
- IEEE 754 compliant where hardware supports it
- No guaranteed behavior on platforms without FPU
- `f32` and `f64` only — no extended precision

### Memory Alignment
- Structs are packed by default
- No alignment annotations (yet)
- Platform ABI determines actual layout

---

## Error Messages for Limitations

When you hit a limitation, the compiler provides specific errors:

| Error Code | Meaning |
|------------|---------|
| `E_UNBOUNDED_LOOP` | Loop without determinable bound |
| `E_WHILE_REMOVED` | `while` loops are rejected |
| `E_MISSING_RECURSION_ANNOTATION` | Recursive function needs `@recursion(max=N)` |
| `E_UNBOUNDED_HEAP` | Allocation size not compile-time constant |
| `E_EXTERN_STACK_REQUIRED` | `extern fn` must declare `@stack(N)` |
| `E_INDEX_OUT_OF_BOUNDS` | Array access exceeds declared size |
| `E_EXTERN_VARIADIC` | Variadic extern functions not supported |
| `E_TYPE_MISMATCH` | Explicit type annotation required |

---

## Future Considerations

Features under consideration for future versions:
- Basic generics for collection types
- Compile-time evaluation (constexpr)
- Enum with associated data
- Basic pattern matching
- Inline assembly blocks
- Alignment annotations
