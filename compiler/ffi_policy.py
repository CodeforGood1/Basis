"""
BASIS foreign-library trust policy.

This stage validates that user-facing `extern fn` declarations are tied to an
explicit foreign library identity, resolves that library against a manifest, and
enforces compiler policy over trusted/reviewed/unverified/unsafe libraries.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, Optional, Set

from ast_defs import Annotation, FunctionDecl, LiteralExpr, Module
from consteval import ConstantEvaluator
from diagnostics import DiagnosticEngine


TRUST_LEVELS = {"trusted", "reviewed", "unverified", "unsafe"}
POLICY_MODES = {"strict", "warn", "allow"}


class FfiPolicyError(ValueError):
    """Raised when an FFI manifest or policy configuration is invalid."""


@dataclass(frozen=True)
class FfiLibrarySpec:
    library_id: str
    trust: str
    requires_wrappers: bool = False
    notes: str = ""
    allow_in_strict: Optional[bool] = None
    provenance: str = "<builtin>"

    @property
    def strict_allowed(self) -> bool:
        if self.allow_in_strict is not None:
            return self.allow_in_strict
        return self.trust in {"trusted", "reviewed"}


@dataclass(frozen=True)
class FfiResolvedExtern:
    module_name: str
    function_name: str
    symbol_name: str
    library_id: str
    trust: str
    requires_wrappers: bool
    strict_allowed: bool
    notes: str
    manifest_found: bool
    provenance: str

    def qualified_name(self) -> str:
        return f"{self.module_name}::{self.function_name}"


@dataclass(frozen=True)
class FfiPolicyConfig:
    mode: str = "strict"
    manifest_path: Optional[str] = None

    def __post_init__(self):
        if self.mode not in POLICY_MODES:
            raise FfiPolicyError(
                f"unsupported FFI policy '{self.mode}'. Supported modes: {', '.join(sorted(POLICY_MODES))}"
            )


class FfiManifest:
    def __init__(self, libraries: Optional[Dict[str, FfiLibrarySpec]] = None):
        self.libraries: Dict[str, FfiLibrarySpec] = dict(libraries or {})

    def merge(self, other: "FfiManifest") -> "FfiManifest":
        merged = dict(self.libraries)
        merged.update(other.libraries)
        return FfiManifest(merged)

    def get(self, library_id: str) -> Optional[FfiLibrarySpec]:
        return self.libraries.get(library_id)

    @classmethod
    def from_file(cls, manifest_path: Path) -> "FfiManifest":
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FfiPolicyError(f"FFI manifest file not found: {manifest_path}") from exc
        except json.JSONDecodeError as exc:
            raise FfiPolicyError(f"invalid FFI manifest JSON in {manifest_path}: {exc}") from exc

        if not isinstance(data, dict):
            raise FfiPolicyError(f"FFI manifest {manifest_path} must contain a JSON object")
        libraries_node = data.get("libraries", data)
        if not isinstance(libraries_node, dict):
            raise FfiPolicyError(f"FFI manifest {manifest_path} must define a 'libraries' object")

        libraries: Dict[str, FfiLibrarySpec] = {}
        for library_id, raw_spec in libraries_node.items():
            if not isinstance(raw_spec, dict):
                raise FfiPolicyError(
                    f"FFI manifest entry '{library_id}' in {manifest_path} must be an object"
                )
            trust = raw_spec.get("trust", "unverified")
            if trust not in TRUST_LEVELS:
                raise FfiPolicyError(
                    f"FFI manifest entry '{library_id}' in {manifest_path} has invalid trust '{trust}'"
                )
            libraries[library_id] = FfiLibrarySpec(
                library_id=library_id,
                trust=trust,
                requires_wrappers=bool(raw_spec.get("requires_wrappers", False)),
                notes=str(raw_spec.get("notes", "")),
                allow_in_strict=(
                    bool(raw_spec["allow_in_strict"]) if "allow_in_strict" in raw_spec else None
                ),
                provenance=str(manifest_path),
            )
        return cls(libraries)


def load_ffi_manifest(optional_manifest: Optional[str] = None) -> FfiManifest:
    builtin_manifest = FfiManifest.from_file(Path(__file__).with_name("ffi_manifest_builtin.json"))
    if not optional_manifest:
        return builtin_manifest
    user_manifest = FfiManifest.from_file(Path(optional_manifest))
    return builtin_manifest.merge(user_manifest)


def validate_ffi_bindings(
    *,
    modules: Dict[str, Module],
    module_paths: Dict[str, str],
    stdlib_modules: Set[str],
    const_evaluators: Dict[str, ConstantEvaluator],
    diag: DiagnosticEngine,
    policy: FfiPolicyConfig,
) -> Dict[str, FfiResolvedExtern]:
    manifest = load_ffi_manifest(policy.manifest_path)
    resolved: Dict[str, FfiResolvedExtern] = {}

    for module_name, module in modules.items():
        module_is_strict = bool(module.directives.get("strict"))
        for decl in module.declarations:
            if not isinstance(decl, FunctionDecl) or not decl.is_extern:
                continue

            library_id = _resolve_library_id(
                decl=decl,
                module_name=module_name,
                module_path=module_paths.get(module_name, f"<{module_name}>"),
                is_stdlib_module=(module_name in stdlib_modules),
                const_eval=const_evaluators[module_name],
                diag=diag,
            )
            if library_id is None:
                continue

            spec = manifest.get(library_id)
            manifest_found = spec is not None
            if spec is None:
                spec = FfiLibrarySpec(
                    library_id=library_id,
                    trust="unverified",
                    notes="no manifest entry was found for this foreign library",
                    provenance="<implicit>",
                )

            binding = FfiResolvedExtern(
                module_name=module_name,
                function_name=decl.name,
                symbol_name=decl.extern_symbol or decl.name,
                library_id=library_id,
                trust=spec.trust,
                requires_wrappers=spec.requires_wrappers,
                strict_allowed=spec.strict_allowed,
                notes=spec.notes,
                manifest_found=manifest_found,
                provenance=spec.provenance,
            )
            resolved[binding.qualified_name()] = binding

            if spec.requires_wrappers and (decl.visibility or "private") == "public":
                _report(
                    diag,
                    severity="error",
                    code="E_FFI_WRAPPER_REQUIRED",
                    message=(
                        f"extern function '{decl.name}' targets foreign library '{library_id}', "
                        "which must stay private and be wrapped by a BASIS function"
                    ),
                    module_name=module_name,
                    span=_annotation_span_or_decl(decl, "ffi"),
                )

            severity, code = _classify_policy_outcome(binding, policy.mode, module_is_strict)
            if severity is None or code is None:
                continue
            _report(
                diag,
                severity=severity,
                code=code,
                message=_policy_message(binding, module_is_strict),
                module_name=module_name,
                span=_annotation_span_or_decl(decl, "ffi"),
            )

    return resolved


def _resolve_library_id(
    *,
    decl: FunctionDecl,
    module_name: str,
    module_path: str,
    is_stdlib_module: bool,
    const_eval: ConstantEvaluator,
    diag: DiagnosticEngine,
) -> Optional[str]:
    ffi_annotation = _find_annotation(decl.annotations, "ffi")
    if ffi_annotation is not None:
        library_expr = None
        if ffi_annotation.arguments:
            for key in ("lib", "library", "value"):
                if key in ffi_annotation.arguments:
                    library_expr = ffi_annotation.arguments[key]
                    break
        if not isinstance(library_expr, LiteralExpr) or library_expr.kind != "string" or not library_expr.value:
            _report(
                diag,
                severity="error",
                code="E_FFI_ANNOTATION_INVALID",
                message=f"extern function '{decl.name}' requires @ffi(lib=\"...\") with a non-empty string literal",
                module_name=module_name,
                span=ffi_annotation.span,
            )
            return None
        return str(library_expr.value)

    if is_stdlib_module:
        return f"basis.{module_name}"

    _report(
        diag,
        severity="error",
        code="E_EXTERN_FFI_LIBRARY_REQUIRED",
        message=(
            f"extern function '{decl.name}' in '{module_path}' must declare @ffi(lib=\"...\") "
            "or be provided by the BASIS standard library"
        ),
        module_name=module_name,
        span=decl.span,
    )
    return None


def _classify_policy_outcome(
    binding: FfiResolvedExtern,
    policy_mode: str,
    module_is_strict: bool,
) -> tuple[Optional[str], Optional[str]]:
    if binding.trust in {"trusted", "reviewed"}:
        if module_is_strict and not binding.strict_allowed:
            return ("error", "E_FFI_STRICT_LIBRARY")
        return (None, None)

    if module_is_strict:
        return ("error", "E_FFI_STRICT_LIBRARY")

    if binding.trust == "unsafe":
        if policy_mode == "strict":
            return ("error", "E_FFI_UNSAFE_LIBRARY")
        return ("warning", "W_FFI_UNSAFE_LIBRARY")

    if policy_mode == "strict":
        return ("error", "E_FFI_UNVERIFIED_LIBRARY")
    if policy_mode == "warn":
        return ("warning", "W_FFI_UNVERIFIED_LIBRARY")
    return (None, None)


def _policy_message(binding: FfiResolvedExtern, module_is_strict: bool) -> str:
    strict_suffix = " in a strict module" if module_is_strict else ""
    base = (
        f"foreign library '{binding.library_id}' is {binding.trust}{strict_suffix}; "
        f"symbol '{binding.function_name}' is bound via {binding.provenance}"
    )
    if binding.notes:
        base = f"{base}. {binding.notes}"
    if not binding.manifest_found:
        base = (
            f"{base}. Add an FFI manifest entry or lower the compiler policy if this dependency is intentional."
        )
    return base


def _annotation_span_or_decl(decl: FunctionDecl, annotation_name: str):
    annotation = _find_annotation(decl.annotations, annotation_name)
    return annotation.span if annotation is not None else decl.span


def _find_annotation(annotations, name: str) -> Optional[Annotation]:
    for annotation in annotations:
        if annotation.name == name:
            return annotation
    return None


def _report(diag: DiagnosticEngine, *, severity: str, code: str, message: str, module_name: str, span):
    filename = f"<{module_name}>"
    if severity == "error":
        diag.error(code, message, span.start_line, span.start_col, filename=filename)
        return
    diag.warning(code, message, span.start_line, span.start_col, filename=filename)
