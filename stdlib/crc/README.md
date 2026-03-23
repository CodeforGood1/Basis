# BASIS Stdlib: `crc`

Fixed-size checksum and CRC helpers for deterministic packet processing.

## Good Use Cases

- sensor packet validation
- serial framing
- fieldbus or UART payload integrity checks
- small embedded protocol helpers

The current library intentionally targets fixed packet sizes because BASIS does not yet have generics or slices.

## API

| Function | Description |
|----------|-------------|
| `crc8_update(crc, byte)` | One-byte CRC-8 update |
| `crc8_u8x8(data)` | CRC-8 over an 8-byte packet |
| `crc8_u8x16(data)` | CRC-8 over a 16-byte packet |
| `crc16_modbus_update(crc, byte)` | One-byte MODBUS CRC-16 update |
| `crc16_modbus_u8x8(data)` | CRC-16 over an 8-byte packet |
| `crc16_modbus_u8x16(data)` | CRC-16 over a 16-byte packet |
