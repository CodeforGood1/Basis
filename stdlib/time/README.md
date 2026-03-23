# BASIS Standard Library - Time

Rollover-safe helpers for unsigned tick counters.

These helpers are intended for long-uptime embedded systems where a `u32`
counter eventually wraps and naive `now >= deadline` comparisons become wrong.

Example:

```basis
import time::*;

let start: u32 = 0xFFFF_FFF0 as u32;
let deadline: u32 = deadline_from_u32(start, 32 as u32);
let now: u32 = 0x0000_0008 as u32;

if deadline_reached_u32(now, deadline) {
    // Safe even across wraparound
}
```
