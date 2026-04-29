"""
Target build/flash plan generation.

This module turns emitted backend artifacts plus target-profile metadata into a
real target bundle:
- machine-readable manifest
- PowerShell and POSIX wrapper scripts
- target-specific support scaffolding such as ESP-IDF project files
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence
import json
import os
import shlex

from bir.model import ProgramRuntime
from target_config import TargetLimits


@dataclass(frozen=True)
class PlannedArtifact:
    kind: str
    path: str
    required: bool
    present: bool
    description: str


@dataclass(frozen=True)
class PlannedCommand:
    description: str
    steps: List[List[str]]
    workdir: str
    enabled: bool = True
    reason: Optional[str] = None


@dataclass(frozen=True)
class TargetBundleManifest:
    schema_version: int
    program: str
    backend: str
    target_key: str
    target_name: str
    target_triple: str
    target_abi: str
    startup_model: str
    sdk_integration: str
    build_system: str
    artifact_format: str
    supports_host_run: bool
    startup_objects: List[str]
    linker_script_required: bool
    linker_script_expected: Optional[str]
    notes: List[str] = field(default_factory=list)
    artifacts: List[PlannedArtifact] = field(default_factory=list)
    build: Optional[PlannedCommand] = None
    flash: Optional[PlannedCommand] = None
    run: Optional[PlannedCommand] = None


def write_target_bundle(
    *,
    output_dir: Path,
    program_name: str,
    backend: str,
    target: TargetLimits,
    runtime: ProgramRuntime,
    binary_path: Optional[Path] = None,
    is_library: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _build_manifest(
        output_dir=output_dir,
        program_name=program_name,
        backend=backend,
        target=target,
        runtime=runtime,
        binary_path=binary_path,
        is_library=is_library,
    )
    _write_support_files(output_dir, manifest, target=target, backend=backend)
    manifest_path = output_dir / "basis-target-manifest.json"
    manifest_path.write_text(json.dumps(_render_manifest(manifest), indent=2), encoding="utf-8")
    _write_script(output_dir / "basis-build-target.ps1", _render_powershell(manifest.build))
    _write_script(output_dir / "basis-build-target.sh", _render_shell(manifest.build))
    if manifest.flash is not None:
        _write_script(output_dir / "basis-flash-target.ps1", _render_powershell(manifest.flash))
        _write_script(output_dir / "basis-flash-target.sh", _render_shell(manifest.flash))
    if manifest.run is not None:
        _write_script(output_dir / "basis-run-target.ps1", _render_powershell(manifest.run))
        _write_script(output_dir / "basis-run-target.sh", _render_shell(manifest.run))
    return manifest_path


def _build_manifest(
    *,
    output_dir: Path,
    program_name: str,
    backend: str,
    target: TargetLimits,
    runtime: ProgramRuntime,
    binary_path: Optional[Path],
    is_library: bool,
) -> TargetBundleManifest:
    artifacts = _collect_artifacts(output_dir, binary_path=binary_path)
    notes: List[str] = []

    if is_library:
        notes.append("Library builds do not produce a target entry wrapper or flashable image.")
    if target.build_system == "esp-idf" and backend == "llvm":
        notes.append(
            "ESP-IDF integration is C-native. LLVM target plans emit compile/link wrappers, "
            "but SDK packaging is still centered on the C backend bundle."
        )
    if target.linker_script_required and target.build_system != "esp-idf":
        notes.append(
            "Replace target-support/linker_script.ld.template with a board-specific linker "
            "script at target-support/linker_script.ld before running the build wrapper."
        )
    if target.startup_objects and target.build_system != "esp-idf":
        notes.append(
            "Place target startup objects under target-support/startup/ before running the build wrapper."
        )

    build = None if is_library else _build_command(
        output_dir=output_dir,
        program_name=program_name,
        backend=backend,
        target=target,
        artifacts=artifacts,
    )
    flash = None if is_library else _flash_command(
        output_dir=output_dir,
        program_name=program_name,
        backend=backend,
        target=target,
    )
    run = None if is_library else _run_command(
        output_dir=output_dir,
        program_name=program_name,
        target=target,
        binary_path=binary_path,
    )

    linker_expected = None
    if target.linker_script_required and target.build_system != "esp-idf":
        linker_expected = "target-support/linker_script.ld"

    return TargetBundleManifest(
        schema_version=1,
        program=program_name,
        backend=backend,
        target_key=target.key,
        target_name=target.name,
        target_triple=runtime.target_triple,
        target_abi=runtime.target_abi,
        startup_model=runtime.startup_model,
        sdk_integration=target.sdk_integration,
        build_system=target.build_system,
        artifact_format=target.artifact_format,
        supports_host_run=runtime.supports_host_run,
        startup_objects=list(target.startup_objects),
        linker_script_required=target.linker_script_required,
        linker_script_expected=linker_expected,
        notes=notes,
        artifacts=artifacts,
        build=build,
        flash=flash,
        run=run,
    )


def _collect_artifacts(output_dir: Path, *, binary_path: Optional[Path]) -> List[PlannedArtifact]:
    artifacts: List[PlannedArtifact] = []
    seen: set[str] = set()

    def add(kind: str, path: Path, required: bool, description: str):
        rel = path.relative_to(output_dir).as_posix() if path.is_absolute() and output_dir in path.parents else path.name
        if rel in seen:
            return
        seen.add(rel)
        artifacts.append(
            PlannedArtifact(
                kind=kind,
                path=rel,
                required=required,
                present=path.exists(),
                description=description,
            )
        )

    for c_file in sorted(output_dir.glob("*.c")):
        add("c_source", c_file, False, "Generated C translation unit.")
    for header in sorted(output_dir.glob("*.h")):
        add("c_header", header, False, "Generated C header.")
    for mlir in sorted(output_dir.glob("*.mlir")):
        add("mlir", mlir, False, "Generated MLIR lowering artifact.")
    for llvm_ir in sorted(output_dir.glob("*.ll")):
        add("llvm_ir", llvm_ir, False, "Generated LLVM IR module.")
    for obj in sorted(output_dir.glob("*.o")):
        add("object", obj, False, "Generated object file.")
    if binary_path is not None:
        add("binary", binary_path, False, "Generated host-linked executable.")
    return artifacts


def _build_command(
    *,
    output_dir: Path,
    program_name: str,
    backend: str,
    target: TargetLimits,
    artifacts: Sequence[PlannedArtifact],
) -> Optional[PlannedCommand]:
    if target.build_system == "esp-idf" and backend == "c":
        project_dir = output_dir / "esp32_project"
        return PlannedCommand(
            description="Build the generated ESP-IDF project.",
            steps=[["idf.py", "-C", str(project_dir), "build"]],
            workdir=str(output_dir),
        )

    if target.build_system == "esp-idf" and backend != "c":
        ll_paths = [artifact.path for artifact in artifacts if artifact.kind == "llvm_ir"]
        if not ll_paths:
            return PlannedCommand(
                description="No LLVM IR artifact was emitted for ESP32 build planning.",
                steps=[],
                workdir=str(output_dir),
                enabled=False,
                reason="missing LLVM IR artifact",
            )
        output_object = f"{program_name}.o"
        output_elf = f"{program_name}.elf"
        linker_script = "target-support/linker_script.ld"
        startup_args = [f"target-support/startup/{name}" for name in target.startup_objects]
        return PlannedCommand(
            description="Compile and link the generated LLVM IR for ESP32 with the Xtensa toolchain.",
            steps=[
                [target.llvm_compiler, f"--target={target.triple}", "-c", ll_paths[0], "-o", output_object],
                [
                    target.linker or target.c_compiler,
                    *startup_args,
                    output_object,
                    "-T",
                    linker_script,
                    "-o",
                    output_elf,
                ],
            ],
            workdir=str(output_dir),
        )

    if target.artifact_format == "exe":
        executable_name = _host_executable_name(program_name)
    else:
        executable_name = f"{program_name}.{target.artifact_format}"

    c_sources = [artifact.path for artifact in artifacts if artifact.kind == "c_source"]
    llvm_ir = [artifact.path for artifact in artifacts if artifact.kind == "llvm_ir"]
    objects = [artifact.path for artifact in artifacts if artifact.kind == "object"]

    if backend == "c":
        if not c_sources:
            return PlannedCommand(
                description="No C sources were emitted for this target plan.",
                steps=[],
                workdir=str(output_dir),
                enabled=False,
                reason="missing C sources",
            )
        step = [target.c_compiler, "-std=c99", *target.arch_flags, *c_sources]
        if target.linker_script_required:
            step.extend(["-T", "target-support/linker_script.ld"])
        step.extend(f"target-support/startup/{name}" for name in target.startup_objects)
        step.extend(["-Wl,-Map", f"{program_name}.map", "-o", executable_name])
        return PlannedCommand(
            description="Compile and link generated C sources for the selected target.",
            steps=[step],
            workdir=str(output_dir),
        )

    if backend == "llvm":
        steps: List[List[str]] = []
        output_object = f"{program_name}.o"
        if not objects:
            if not llvm_ir:
                return PlannedCommand(
                    description="No LLVM artifacts were emitted for this target plan.",
                    steps=[],
                    workdir=str(output_dir),
                    enabled=False,
                    reason="missing LLVM IR and object files",
                )
            compile_step = [target.llvm_compiler]
            if target.triple != "native":
                compile_step.append(f"--target={target.triple}")
            compile_step.extend([*target.arch_flags, "-c", llvm_ir[0], "-o", output_object])
            steps.append(compile_step)
            object_inputs = [output_object]
        else:
            object_inputs = objects
        link_step = [target.linker or target.c_compiler, *target.arch_flags]
        if target.linker_script_required:
            link_step.extend(["-T", "target-support/linker_script.ld"])
        link_step.extend(f"target-support/startup/{name}" for name in target.startup_objects)
        link_step.extend([*object_inputs, "-Wl,-Map", f"{program_name}.map", "-o", executable_name])
        steps.append(link_step)
        return PlannedCommand(
            description="Compile and link generated LLVM artifacts for the selected target.",
            steps=steps,
            workdir=str(output_dir),
        )

    return None


def _flash_command(
    *,
    output_dir: Path,
    program_name: str,
    backend: str,
    target: TargetLimits,
) -> Optional[PlannedCommand]:
    if target.flash_runner is None or target.flash_command is None:
        return None

    artifact = f"{program_name}.{target.artifact_format}"
    if target.build_system == "esp-idf" and backend == "c":
        project_dir = output_dir / "esp32_project"
        return PlannedCommand(
            description="Flash the generated ESP-IDF project to the target device.",
            steps=[["idf.py", "-C", str(project_dir), "flash"]],
            workdir=str(output_dir),
        )

    command = target.flash_command.format(artifact=artifact, port="$PORT")
    return PlannedCommand(
        description="Flash the generated target artifact.",
        steps=[_split_command(command)],
        workdir=str(output_dir),
    )


def _run_command(
    *,
    output_dir: Path,
    program_name: str,
    target: TargetLimits,
    binary_path: Optional[Path],
) -> Optional[PlannedCommand]:
    if not target.supports_host_run:
        return None
    if binary_path is None:
        executable_name = _host_executable_name(program_name)
    else:
        executable_name = binary_path.name
    return PlannedCommand(
        description="Run the host-linked program.",
        steps=[[str((output_dir / executable_name).resolve())]],
        workdir=str(output_dir),
    )


def _write_support_files(
    output_dir: Path,
    manifest: TargetBundleManifest,
    *,
    target: TargetLimits,
    backend: str,
):
    target_support = output_dir / "target-support"
    target_support.mkdir(parents=True, exist_ok=True)

    if target.linker_script_required and target.build_system != "esp-idf":
        template_path = target_support / "linker_script.ld.template"
        template_path.write_text(
            _linker_template(target),
            encoding="utf-8",
        )
        _write_placeholder_artifact(
            manifest,
            kind="support",
            path="target-support/linker_script.ld.template",
            description="Board-specific linker script template to customize before building.",
        )

    if target.startup_objects and target.build_system != "esp-idf":
        startup_dir = target_support / "startup"
        startup_dir.mkdir(parents=True, exist_ok=True)
        (startup_dir / "README.txt").write_text(
            _startup_readme(target),
            encoding="utf-8",
        )
        _write_placeholder_artifact(
            manifest,
            kind="support",
            path="target-support/startup/README.txt",
            description="List of startup objects expected by the generated target build wrapper.",
        )

    if target.build_system == "esp-idf" and backend == "c":
        _write_esp_idf_project(output_dir, manifest.program)
        _write_placeholder_artifact(
            manifest,
            kind="support",
            path="esp32_project/CMakeLists.txt",
            description="Generated ESP-IDF project root.",
        )
        _write_placeholder_artifact(
            manifest,
            kind="support",
            path="esp32_project/main/CMakeLists.txt",
            description="Generated ESP-IDF component description for emitted C files.",
        )
        _write_placeholder_artifact(
            manifest,
            kind="support",
            path="esp32_project/main/idf_component.yml",
            description="Generated ESP-IDF component manifest.",
        )


def _write_esp_idf_project(output_dir: Path, program_name: str):
    project_dir = output_dir / "esp32_project"
    main_dir = project_dir / "main"
    project_dir.mkdir(parents=True, exist_ok=True)
    main_dir.mkdir(parents=True, exist_ok=True)

    source_lines = []
    for c_file in sorted(output_dir.glob("*.c")):
        source_lines.append(f'    "../../{c_file.name}"')
    if not source_lines:
        source_lines.append('    "../missing_source.c"')

    (project_dir / "CMakeLists.txt").write_text(
        "\n".join(
            [
                "cmake_minimum_required(VERSION 3.16)",
                "include($ENV{IDF_PATH}/tools/cmake/project.cmake)",
                f"project({program_name})",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (main_dir / "CMakeLists.txt").write_text(
        "\n".join(
            [
                "idf_component_register(",
                "  SRCS",
                *source_lines,
                '  INCLUDE_DIRS "../.."',
                ")",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (main_dir / "idf_component.yml").write_text(
        "version: '1.0.0'\ndescription: Generated BASIS component\n",
        encoding="utf-8",
    )


def _linker_template(target: TargetLimits) -> str:
    return "\n".join(
        [
            "/*",
            f"  BASIS linker script template for {target.name}.",
            "  Replace this template with a board-specific memory map and save it as",
            "  target-support/linker_script.ld before running the build wrapper.",
            "*/",
            "",
            "MEMORY",
            "{",
            "  FLASH (rx) : ORIGIN = 0x00000000, LENGTH = 0x00000000",
            "  RAM   (rwx): ORIGIN = 0x00000000, LENGTH = 0x00000000",
            "}",
            "",
            "SECTIONS",
            "{",
            "  .text : { *(.text*) *(.rodata*) } > FLASH",
            "  .data : { *(.data*) } > RAM AT > FLASH",
            "  .bss  : { *(.bss*) *(COMMON) } > RAM",
            "}",
            "",
        ]
    )


def _startup_readme(target: TargetLimits) -> str:
    lines = [
        f"BASIS target startup object expectations for {target.name}:",
        "",
    ]
    for name in target.startup_objects:
        lines.append(f"- {name}")
    lines.append("")
    lines.append("Place the required object files in this directory before running the build wrapper.")
    return "\n".join(lines)


def _write_placeholder_artifact(
    manifest: TargetBundleManifest,
    *,
    kind: str,
    path: str,
    description: str,
):
    for artifact in manifest.artifacts:
        if artifact.path == path:
            return
    manifest.artifacts.append(
        PlannedArtifact(
            kind=kind,
            path=path,
            required=False,
            present=True,
            description=description,
        )
    )


def _render_manifest(manifest: TargetBundleManifest) -> Dict[str, object]:
    return asdict(manifest)


def _render_powershell(command: Optional[PlannedCommand]) -> str:
    if command is None:
        return _disabled_script("No command is defined for this target action.")
    lines = [
        "param()",
        '$ErrorActionPreference = "Stop"',
        "",
    ]
    if not command.enabled:
        lines.append(f'throw "{command.reason or "This action is disabled."}"')
        lines.append("")
        return "\n".join(lines)
    lines.append(f'Set-Location "{command.workdir}"')
    lines.append("")
    for step in command.steps:
        rendered = " ".join(_quote_powershell(token) for token in step)
        lines.append(f"& {rendered}")
        lines.append("if ($LASTEXITCODE -ne 0) {")
        lines.append(f'    throw "{command.description} failed."')
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


def _render_shell(command: Optional[PlannedCommand]) -> str:
    if command is None:
        return _disabled_shell("No command is defined for this target action.")
    lines = [
        "#!/usr/bin/env sh",
        "set -eu",
        "",
    ]
    if not command.enabled:
        lines.append(f'echo "{command.reason or "This action is disabled."}" >&2')
        lines.append("exit 1")
        lines.append("")
        return "\n".join(lines)
    lines.append(f"cd {shlex.quote(command.workdir)}")
    lines.append("")
    for step in command.steps:
        lines.append(" ".join(shlex.quote(token) for token in step))
    lines.append("")
    return "\n".join(lines)


def _disabled_script(message: str) -> str:
    return "\n".join(["param()", '$ErrorActionPreference = "Stop"', f'throw "{message}"', ""])


def _disabled_shell(message: str) -> str:
    return "\n".join(["#!/usr/bin/env sh", "set -eu", f'echo "{message}" >&2', "exit 1", ""])


def _write_script(path: Path, content: str):
    path.write_text(content, encoding="utf-8")
    if path.suffix == ".sh":
        try:
            current_mode = path.stat().st_mode
            path.chmod(current_mode | 0o111)
        except OSError:
            pass


def _quote_powershell(token: str) -> str:
    return "'" + token.replace("'", "''") + "'"


def _split_command(command: str) -> List[str]:
    if os.name == "nt":
        return shlex.split(command, posix=False)
    return shlex.split(command)


def _host_executable_name(program_name: str) -> str:
    return f"{program_name}.exe" if os.name == "nt" else program_name
