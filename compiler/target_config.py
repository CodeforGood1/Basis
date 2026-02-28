"""
BASIS Target Configuration
Defines resource constraints for target platforms.
"""

from dataclasses import dataclass
from typing import Optional, Dict
from pathlib import Path
import json


@dataclass
class TargetLimits:
    """Resource limits for a target platform."""
    name: str
    ram_bytes: int
    flash_bytes: int
    stack_bytes: int
    heap_bytes: Optional[int] = None  # None = use remaining RAM
    
    def __repr__(self):
        return (f"Target({self.name}: RAM={self._format_size(self.ram_bytes)}, "
                f"Flash={self._format_size(self.flash_bytes)}, "
                f"Stack={self._format_size(self.stack_bytes)})")
    
    @staticmethod
    def _format_size(bytes_val: int) -> str:
        """Format byte size in human-readable form."""
        if bytes_val >= 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f}MB"
        elif bytes_val >= 1024:
            return f"{bytes_val / 1024:.1f}KB"
        else:
            return f"{bytes_val}B"


# Predefined target platforms
PREDEFINED_TARGETS: Dict[str, TargetLimits] = {
    "stm32f103": TargetLimits(
        name="STM32F103 (Blue Pill)",
        ram_bytes=20 * 1024,      # 20KB RAM
        flash_bytes=64 * 1024,    # 64KB Flash
        stack_bytes=2 * 1024,     # 2KB Stack
    ),
    "stm32f407": TargetLimits(
        name="STM32F407 Discovery",
        ram_bytes=128 * 1024,     # 128KB RAM
        flash_bytes=1024 * 1024,  # 1MB Flash
        stack_bytes=8 * 1024,     # 8KB Stack
    ),
    "esp32": TargetLimits(
        name="ESP32",
        ram_bytes=520 * 1024,     # 520KB RAM
        flash_bytes=4 * 1024 * 1024,  # 4MB Flash
        stack_bytes=8 * 1024,     # 8KB Stack
    ),
    "arduino_uno": TargetLimits(
        name="Arduino Uno (ATmega328P)",
        ram_bytes=2 * 1024,       # 2KB RAM
        flash_bytes=32 * 1024,    # 32KB Flash
        stack_bytes=256,          # 256B Stack
    ),
    "raspberry_pi_pico": TargetLimits(
        name="Raspberry Pi Pico (RP2040)",
        ram_bytes=264 * 1024,     # 264KB RAM
        flash_bytes=2 * 1024 * 1024,  # 2MB Flash
        stack_bytes=16 * 1024,    # 16KB Stack
    ),
    "host": TargetLimits(
        name="Host PC (development)",
        ram_bytes=128 * 1024 * 1024,      # 128MB (generous for dev)
        flash_bytes=1024 * 1024 * 1024,   # 1GB (not really limited)
        stack_bytes=1 * 1024 * 1024,      # 1MB Stack
    ),
}


class TargetConfig:
    """Manages target configuration for compilation."""
    
    def __init__(self, target: Optional[TargetLimits] = None):
        self.target = target or PREDEFINED_TARGETS["host"]
    
    @classmethod
    def from_name(cls, name: str) -> 'TargetConfig':
        """Create config from predefined target name."""
        if name not in PREDEFINED_TARGETS:
            available = ", ".join(PREDEFINED_TARGETS.keys())
            raise ValueError(f"Unknown target '{name}'. Available targets: {available}")
        return cls(PREDEFINED_TARGETS[name])
    
    @classmethod
    def from_file(cls, config_file: Path) -> 'TargetConfig':
        """Load target configuration from JSON file."""
        with open(config_file, 'r') as f:
            data = json.load(f)
        
        target = TargetLimits(
            name=data.get("name", "custom"),
            ram_bytes=cls._parse_size(data["ram"]),
            flash_bytes=cls._parse_size(data["flash"]),
            stack_bytes=cls._parse_size(data["stack"]),
            heap_bytes=cls._parse_size(data["heap"]) if "heap" in data else None,
        )
        return cls(target)
    
    @staticmethod
    def _parse_size(size_str: str) -> int:
        """Parse size string like '20KB', '1MB', '256' to bytes."""
        size_str = str(size_str).strip().upper()
        
        if size_str.endswith('GB'):
            return int(float(size_str[:-2]) * 1024 * 1024 * 1024)
        elif size_str.endswith('MB'):
            return int(float(size_str[:-2]) * 1024 * 1024)
        elif size_str.endswith('KB'):
            return int(float(size_str[:-2]) * 1024)
        elif size_str.endswith('B'):
            return int(size_str[:-1])
        else:
            return int(size_str)
    
    def validate_resources(self, total_stack: int, total_heap: int, 
                          code_size: int) -> Optional[str]:
        """
        Validate resource usage against target limits.
        Returns error message if limits exceeded, None if OK.
        """
        errors = []
        
        # Check stack
        if total_stack > self.target.stack_bytes:
            errors.append(
                f"Stack overflow: {total_stack}B used > "
                f"{self.target.stack_bytes}B available"
            )
        
        # Check heap
        heap_limit = self.target.heap_bytes or (
            self.target.ram_bytes - self.target.stack_bytes
        )
        if total_heap > heap_limit:
            errors.append(
                f"Heap overflow: {total_heap}B used > "
                f"{heap_limit}B available"
            )
        
        # Check total RAM
        total_ram_used = total_stack + total_heap
        if total_ram_used > self.target.ram_bytes:
            errors.append(
                f"RAM overflow: {total_ram_used}B used > "
                f"{self.target.ram_bytes}B available"
            )
        
        # Check flash/code size
        if code_size > self.target.flash_bytes:
            errors.append(
                f"Flash overflow: {code_size}B used > "
                f"{self.target.flash_bytes}B available"
            )
        
        return "\n".join(errors) if errors else None
    
    def get_limits_summary(self) -> str:
        """Get a human-readable summary of target limits."""
        heap_limit = self.target.heap_bytes or (
            self.target.ram_bytes - self.target.stack_bytes
        )
        return f"""Target: {self.target.name}
  RAM:   {TargetLimits._format_size(self.target.ram_bytes)}
  Flash: {TargetLimits._format_size(self.target.flash_bytes)}
  Stack: {TargetLimits._format_size(self.target.stack_bytes)}
  Heap:  {TargetLimits._format_size(heap_limit)}"""
