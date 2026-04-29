"""
BASIS target configuration and build-profile metadata.

Phase 10 extends the target model beyond simple RAM/flash limits so the driver
can generate real build/flash plans per target without letting backend code
invent platform semantics.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple
import json


@dataclass(frozen=True)
class TargetLimits:
    """Resource limits and build integration details for a target platform."""

    key: str
    name: str
    ram_bytes: int
    flash_bytes: int
    stack_bytes: int
    heap_bytes: Optional[int] = None
    entry_symbol: str = "main"
    entry_return: str = "i32"
    startup_model: str = "hosted"
    supports_host_run: bool = True
    triple: str = "native"
    abi: str = "c"
    sdk_integration: str = "native"
    build_system: str = "native"
    c_compiler: str = "gcc"
    llvm_compiler: str = "clang"
    linker: Optional[str] = None
    arch_flags: Tuple[str, ...] = field(default_factory=tuple)
    startup_objects: Tuple[str, ...] = field(default_factory=tuple)
    linker_script: Optional[str] = None
    linker_script_required: bool = False
    flash_runner: Optional[str] = None
    flash_command: Optional[str] = None
    artifact_format: str = "exe"

    def __repr__(self):
        return (
            f"Target({self.name}: RAM={self._format_size(self.ram_bytes)}, "
            f"Flash={self._format_size(self.flash_bytes)}, "
            f"Stack={self._format_size(self.stack_bytes)}, "
            f"Triple={self.triple})"
        )

    @staticmethod
    def _format_size(bytes_val: int) -> str:
        if bytes_val >= 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f}MB"
        if bytes_val >= 1024:
            return f"{bytes_val / 1024:.1f}KB"
        return f"{bytes_val}B"


def _target(
    *,
    key: str,
    name: str,
    ram_bytes: int,
    flash_bytes: int,
    stack_bytes: int,
    heap_bytes: Optional[int] = None,
    entry_symbol: str = "main",
    entry_return: str = "i32",
    startup_model: str = "hosted",
    supports_host_run: bool = True,
    triple: str = "native",
    abi: str = "c",
    sdk_integration: str = "native",
    build_system: str = "native",
    c_compiler: str = "gcc",
    llvm_compiler: str = "clang",
    linker: Optional[str] = None,
    arch_flags: Tuple[str, ...] = (),
    startup_objects: Tuple[str, ...] = (),
    linker_script: Optional[str] = None,
    linker_script_required: bool = False,
    flash_runner: Optional[str] = None,
    flash_command: Optional[str] = None,
    artifact_format: str = "exe",
) -> TargetLimits:
    return TargetLimits(
        key=key,
        name=name,
        ram_bytes=ram_bytes,
        flash_bytes=flash_bytes,
        stack_bytes=stack_bytes,
        heap_bytes=heap_bytes,
        entry_symbol=entry_symbol,
        entry_return=entry_return,
        startup_model=startup_model,
        supports_host_run=supports_host_run,
        triple=triple,
        abi=abi,
        sdk_integration=sdk_integration,
        build_system=build_system,
        c_compiler=c_compiler,
        llvm_compiler=llvm_compiler,
        linker=linker,
        arch_flags=arch_flags,
        startup_objects=startup_objects,
        linker_script=linker_script,
        linker_script_required=linker_script_required,
        flash_runner=flash_runner,
        flash_command=flash_command,
        artifact_format=artifact_format,
    )


PREDEFINED_TARGETS: Dict[str, TargetLimits] = {
    "host": _target(
        key="host",
        name="Host PC (development)",
        ram_bytes=128 * 1024 * 1024,
        flash_bytes=1024 * 1024 * 1024,
        stack_bytes=1 * 1024 * 1024,
        triple="native",
        abi="system",
        sdk_integration="native",
        build_system="native",
        c_compiler="gcc",
        llvm_compiler="clang",
        linker="gcc",
        artifact_format="exe",
    ),
    "embedded_linux": _target(
        key="embedded_linux",
        name="Embedded Linux",
        ram_bytes=256 * 1024 * 1024,
        flash_bytes=64 * 1024 * 1024,
        stack_bytes=1 * 1024 * 1024,
        triple="x86_64-pc-linux-gnu",
        abi="sysv",
        sdk_integration="sysroot",
        build_system="native",
        c_compiler="x86_64-linux-gnu-gcc",
        llvm_compiler="clang",
        linker="x86_64-linux-gnu-gcc",
        artifact_format="elf",
    ),
    "linux": _target(
        key="embedded_linux",
        name="Embedded Linux",
        ram_bytes=256 * 1024 * 1024,
        flash_bytes=64 * 1024 * 1024,
        stack_bytes=1 * 1024 * 1024,
        triple="x86_64-pc-linux-gnu",
        abi="sysv",
        sdk_integration="sysroot",
        build_system="native",
        c_compiler="x86_64-linux-gnu-gcc",
        llvm_compiler="clang",
        linker="x86_64-linux-gnu-gcc",
        artifact_format="elf",
    ),
    "esp32": _target(
        key="esp32",
        name="ESP32",
        ram_bytes=520 * 1024,
        flash_bytes=4 * 1024 * 1024,
        stack_bytes=8 * 1024,
        entry_symbol="app_main",
        entry_return="void",
        startup_model="target_alias",
        supports_host_run=False,
        triple="xtensa-esp32-none-elf",
        abi="xtensa-call0",
        sdk_integration="esp-idf",
        build_system="esp-idf",
        c_compiler="xtensa-esp32-elf-gcc",
        llvm_compiler="clang",
        linker="xtensa-esp32-elf-gcc",
        startup_objects=("crt0.o", "esp32_startup.o"),
        linker_script="esp32_out.ld",
        linker_script_required=True,
        flash_runner="idf.py",
        flash_command="idf.py flash",
        artifact_format="elf",
    ),
    "stm32": _target(
        key="stm32",
        name="STM32 (generic Cortex-M)",
        ram_bytes=128 * 1024,
        flash_bytes=1024 * 1024,
        stack_bytes=8 * 1024,
        supports_host_run=False,
        triple="thumbv7em-none-eabi",
        abi="aapcs",
        sdk_integration="cmsis",
        build_system="baremetal",
        c_compiler="arm-none-eabi-gcc",
        llvm_compiler="clang",
        linker="arm-none-eabi-gcc",
        arch_flags=("-mcpu=cortex-m4", "-mthumb", "-ffreestanding", "-fno-builtin", "-nostdlib"),
        startup_objects=("startup_stm32.o",),
        linker_script="stm32.ld",
        linker_script_required=True,
        flash_runner="openocd",
        flash_command='openocd -f interface/stlink.cfg -f target/stm32.cfg -c "program {artifact} verify reset exit"',
        artifact_format="elf",
    ),
    "stm32f103": _target(
        key="stm32f103",
        name="STM32F103 (Blue Pill)",
        ram_bytes=20 * 1024,
        flash_bytes=64 * 1024,
        stack_bytes=2 * 1024,
        supports_host_run=False,
        triple="thumbv7m-none-eabi",
        abi="aapcs",
        sdk_integration="cmsis",
        build_system="baremetal",
        c_compiler="arm-none-eabi-gcc",
        llvm_compiler="clang",
        linker="arm-none-eabi-gcc",
        arch_flags=("-mcpu=cortex-m3", "-mthumb", "-ffreestanding", "-fno-builtin", "-nostdlib"),
        startup_objects=("startup_stm32f103.o",),
        linker_script="stm32f103.ld",
        linker_script_required=True,
        flash_runner="openocd",
        flash_command='openocd -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program {artifact} verify reset exit"',
        artifact_format="elf",
    ),
    "stm32f407": _target(
        key="stm32f407",
        name="STM32F407 Discovery",
        ram_bytes=128 * 1024,
        flash_bytes=1024 * 1024,
        stack_bytes=8 * 1024,
        supports_host_run=False,
        triple="thumbv7em-none-eabi",
        abi="aapcs",
        sdk_integration="cmsis",
        build_system="baremetal",
        c_compiler="arm-none-eabi-gcc",
        llvm_compiler="clang",
        linker="arm-none-eabi-gcc",
        arch_flags=("-mcpu=cortex-m4", "-mthumb", "-ffreestanding", "-fno-builtin", "-nostdlib"),
        startup_objects=("startup_stm32f407.o",),
        linker_script="stm32f407.ld",
        linker_script_required=True,
        flash_runner="openocd",
        flash_command='openocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c "program {artifact} verify reset exit"',
        artifact_format="elf",
    ),
    "rp2040": _target(
        key="rp2040",
        name="RP2040",
        ram_bytes=264 * 1024,
        flash_bytes=2 * 1024 * 1024,
        stack_bytes=16 * 1024,
        supports_host_run=False,
        triple="thumbv6m-none-eabi",
        abi="aapcs",
        sdk_integration="pico-sdk",
        build_system="cmake",
        c_compiler="arm-none-eabi-gcc",
        llvm_compiler="clang",
        linker="arm-none-eabi-gcc",
        arch_flags=("-mcpu=cortex-m0plus", "-mthumb", "-ffreestanding", "-fno-builtin", "-nostdlib"),
        startup_objects=("crt0.o",),
        linker_script="rp2040.ld",
        linker_script_required=True,
        flash_runner="picotool",
        flash_command="picotool load {artifact} -x",
        artifact_format="elf",
    ),
    "raspberry_pi_pico": _target(
        key="rp2040",
        name="RP2040",
        ram_bytes=264 * 1024,
        flash_bytes=2 * 1024 * 1024,
        stack_bytes=16 * 1024,
        supports_host_run=False,
        triple="thumbv6m-none-eabi",
        abi="aapcs",
        sdk_integration="pico-sdk",
        build_system="cmake",
        c_compiler="arm-none-eabi-gcc",
        llvm_compiler="clang",
        linker="arm-none-eabi-gcc",
        arch_flags=("-mcpu=cortex-m0plus", "-mthumb", "-ffreestanding", "-fno-builtin", "-nostdlib"),
        startup_objects=("crt0.o",),
        linker_script="rp2040.ld",
        linker_script_required=True,
        flash_runner="picotool",
        flash_command="picotool load {artifact} -x",
        artifact_format="elf",
    ),
    "arduino_uno": _target(
        key="arduino_uno",
        name="Arduino Uno (ATmega328P)",
        ram_bytes=2 * 1024,
        flash_bytes=32 * 1024,
        stack_bytes=256,
        supports_host_run=False,
        triple="avr-atmel-none",
        abi="avr",
        sdk_integration="arduino",
        build_system="avr-gcc",
        c_compiler="avr-gcc",
        llvm_compiler="clang",
        linker="avr-gcc",
        arch_flags=("-mmcu=atmega328p", "-ffreestanding", "-fno-builtin"),
        startup_objects=("crt1.o",),
        linker_script=None,
        linker_script_required=False,
        flash_runner="avrdude",
        flash_command="avrdude -p m328p -c arduino -P {port} -U flash:w:{artifact}",
        artifact_format="elf",
    ),
}


class TargetConfig:
    """Manages target configuration for compilation and target build planning."""

    def __init__(self, target: Optional[TargetLimits] = None):
        self.target = target or PREDEFINED_TARGETS["host"]

    @classmethod
    def from_name(cls, name: str) -> "TargetConfig":
        if name not in PREDEFINED_TARGETS:
            available = ", ".join(PREDEFINED_TARGETS.keys())
            raise ValueError(f"Unknown target '{name}'. Available targets: {available}")
        return cls(PREDEFINED_TARGETS[name])

    @classmethod
    def from_file(cls, config_file: Path) -> "TargetConfig":
        with open(config_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        target = TargetLimits(
            key=data.get("key", data.get("id", "custom")),
            name=data.get("name", "custom"),
            ram_bytes=cls._parse_size(data["ram"]),
            flash_bytes=cls._parse_size(data["flash"]),
            stack_bytes=cls._parse_size(data["stack"]),
            heap_bytes=cls._parse_size(data["heap"]) if "heap" in data else None,
            entry_symbol=data.get("entry_symbol", "main"),
            entry_return=data.get("entry_return", "i32"),
            startup_model=data.get("startup_model", "hosted"),
            supports_host_run=bool(data.get("supports_host_run", False)),
            triple=data.get("triple", "unknown-unknown-unknown"),
            abi=data.get("abi", "c"),
            sdk_integration=data.get("sdk_integration", "custom"),
            build_system=data.get("build_system", "native"),
            c_compiler=data.get("c_compiler", "gcc"),
            llvm_compiler=data.get("llvm_compiler", "clang"),
            linker=data.get("linker"),
            arch_flags=tuple(data.get("arch_flags", [])),
            startup_objects=tuple(data.get("startup_objects", [])),
            linker_script=data.get("linker_script"),
            linker_script_required=bool(data.get("linker_script_required", False)),
            flash_runner=data.get("flash_runner"),
            flash_command=data.get("flash_command"),
            artifact_format=data.get("artifact_format", "elf"),
        )
        return cls(target)

    @staticmethod
    def _parse_size(size_str: str) -> int:
        size_str = str(size_str).strip().upper()
        if size_str.endswith("GB"):
            return int(float(size_str[:-2]) * 1024 * 1024 * 1024)
        if size_str.endswith("MB"):
            return int(float(size_str[:-2]) * 1024 * 1024)
        if size_str.endswith("KB"):
            return int(float(size_str[:-2]) * 1024)
        if size_str.endswith("B"):
            return int(size_str[:-1])
        return int(size_str)

    def validate_resources(
        self,
        total_stack: int,
        total_heap: int,
        code_size: Optional[int] = None,
    ) -> Optional[str]:
        errors = []

        if total_stack > self.target.stack_bytes:
            errors.append(
                f"Stack overflow: {total_stack}B used > {self.target.stack_bytes}B available"
            )

        heap_limit = self.target.heap_bytes or (self.target.ram_bytes - self.target.stack_bytes)
        if total_heap > heap_limit:
            errors.append(
                f"Heap overflow: {total_heap}B used > {heap_limit}B available"
            )

        total_ram_used = total_stack + total_heap
        if total_ram_used > self.target.ram_bytes:
            errors.append(
                f"RAM overflow: {total_ram_used}B used > {self.target.ram_bytes}B available"
            )

        if code_size is not None and code_size > self.target.flash_bytes:
            errors.append(
                f"Flash overflow: {code_size}B used > {self.target.flash_bytes}B available"
            )

        return "\n".join(errors) if errors else None

    def get_limits_summary(self) -> str:
        heap_limit = self.target.heap_bytes or (self.target.ram_bytes - self.target.stack_bytes)
        startup_objects = ", ".join(self.target.startup_objects) if self.target.startup_objects else "(none)"
        linker_script = self.target.linker_script or "(not required)"
        return f"""Target: {self.target.name}
  Triple: {self.target.triple}
  ABI:    {self.target.abi}
  RAM:    {TargetLimits._format_size(self.target.ram_bytes)}
  Flash:  {TargetLimits._format_size(self.target.flash_bytes)}
  Stack:  {TargetLimits._format_size(self.target.stack_bytes)}
  Heap:   {TargetLimits._format_size(heap_limit)}
  SDK:    {self.target.sdk_integration}
  Build:  {self.target.build_system}
  Start:  {startup_objects}
  Linker: {linker_script}"""
