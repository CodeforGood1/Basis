# BASIS Stdlib: `ring`

Fixed-size deterministic ring buffers for byte-oriented embedded workloads.

## Good Use Cases

- UART receive queues
- packet assembly
- sensor byte streams
- task and callback staging where heap use is undesirable

The current module intentionally uses a fixed 64-byte queue because BASIS does not yet support generics or const generics.

## API

| Function | Description |
|----------|-------------|
| `ring_u8x64_init()` | Returns an empty 64-byte ring buffer |
| `ring_u8x64_capacity()` | Returns the fixed capacity |
| `ring_u8x64_clear(buf)` | Resets the buffer |
| `ring_u8x64_is_empty(buf)` | Returns true if empty |
| `ring_u8x64_is_full(buf)` | Returns true if full |
| `ring_u8x64_count(buf)` | Returns the current item count |
| `ring_u8x64_push(buf, value)` | Pushes one byte, returns false if full |
| `ring_u8x64_pop(buf, out)` | Pops one byte into `out`, returns false if empty |
| `ring_u8x64_peek(buf, out)` | Reads the next byte without consuming it |
