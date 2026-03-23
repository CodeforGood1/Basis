# BASIS Stdlib: `bits`

Helpers for register masks, flags, packed fields, and alignment logic.

## Good Use Cases

- GPIO and peripheral register helpers
- packed protocol headers
- feature flags and bitmasks
- alignment calculations for buffers and memory regions

## API

| Function | Description |
|----------|-------------|
| `bit_mask_u32(bit)` | Returns a one-bit mask at the given position |
| `set_bit_u32(value, bit)` | Sets one bit |
| `clear_bit_u32(value, bit)` | Clears one bit |
| `toggle_bit_u32(value, bit)` | Toggles one bit |
| `test_bit_u32(value, bit)` | Returns true if the bit is set |
| `update_bit_u32(value, bit, enabled)` | Sets or clears a bit based on a boolean |
| `field_get_u32(value, mask, shift)` | Extracts a packed field |
| `field_set_u32(value, mask, shift, field_value)` | Replaces a packed field |
| `align_up_u32(value, alignment)` | Rounds up to a power-of-two alignment |
| `align_down_u32(value, alignment)` | Rounds down to a power-of-two alignment |
| `is_aligned_u32(value, alignment)` | Tests power-of-two alignment |
