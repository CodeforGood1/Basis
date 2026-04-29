param(
    [switch]$VerifyPackage
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Invoke-BasisCheck {
    param(
        [string[]]$CommandArgs,
        [bool]$ExpectSuccess = $true,
        [string[]]$RequiredText = @()
    )

    $hasNativeErrorPreference = Test-Path Variable:PSNativeCommandUseErrorActionPreference
    if ($hasNativeErrorPreference) {
        $previousNativeErrorPreference = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        $output = (& python compiler\basis.py @CommandArgs 2>&1 | Out-String)
        $exitCode = $LASTEXITCODE
    } finally {
        if ($hasNativeErrorPreference) {
            $PSNativeCommandUseErrorActionPreference = $previousNativeErrorPreference
        }
    }

    if ($ExpectSuccess -and $exitCode -ne 0) {
        throw "Command failed: python compiler\basis.py $($CommandArgs -join ' ')`n$output"
    }

    if (-not $ExpectSuccess -and $exitCode -eq 0) {
        throw "Command unexpectedly succeeded: python compiler\basis.py $($CommandArgs -join ' ')`n$output"
    }

    foreach ($text in $RequiredText) {
        if (-not $output.Contains($text)) {
            throw "Expected output to contain '$text'`n$output"
        }
    }

    return $output
}

& python -m py_compile `
    backend_llvm\__init__.py `
    backend_llvm\emitter.py `
    backend_llvm\llvmlite_builder.py `
    backend_llvm\llvm_ir.py `
    backend_llvm\lower.py `
    backend_llvm\verify.py `
    backend_mlir\__init__.py `
    backend_mlir\emitter.py `
    bir\__init__.py `
    bir\lower.py `
    bir\model.py `
    bir\render.py `
    bir\verify.py `
    compiler\basis.py `
    compiler\parser.py `
    compiler\sema.py `
    compiler\loop_analysis.py `
    compiler\resource_analysis.py `
    compiler\codegen.py `
    compiler\ffi_policy.py `
    compiler\target_pipeline.py `
    compiler\module_codegen.py `
    mlir_conversions\__init__.py `
    mlir_conversions\basis_to_llvm.py `
    mlir_conversions\bir_to_basis.py `
    mlir_conversions\canonicalize.py `
    mlir_conversions\type_converter.py `
    mlir_conversions\verify.py `
    mlir_conversions\verify_llvm.py `
    mlir_dialects\__init__.py `
    mlir_dialects\basis.py `
    mlir_dialects\control.py `
    mlir_dialects\extern.py `
    mlir_dialects\isr.py `
    mlir_dialects\llvm.py `
    mlir_dialects\mem.py `
    mlir_dialects\resource.py `
    tests\semantic_regression_checks.py `
    tests\bir_regression_checks.py `
    tests\bir_lowering_regression_checks.py `
    tests\backend_c_regression_checks.py `
    tests\backend_llvm_regression_checks.py `
    tests\backend_mlir_regression_checks.py `
    tests\backend_selection_regression_checks.py `
    tests\backend_equivalence_regression_checks.py `
    tests\target_pipeline_regression_checks.py `
    tests\pipeline_support.py

if ($LASTEXITCODE -ne 0) {
    throw "python -m py_compile failed"
}

& python tests\semantic_regression_checks.py
if ($LASTEXITCODE -ne 0) {
    throw "semantic regression checks failed"
}

& python tests\bir_regression_checks.py
if ($LASTEXITCODE -ne 0) {
    throw "BIR regression checks failed"
}

& python tests\bir_lowering_regression_checks.py
if ($LASTEXITCODE -ne 0) {
    throw "BIR lowering regression checks failed"
}

& python tests\backend_c_regression_checks.py
if ($LASTEXITCODE -ne 0) {
    throw "C backend regression checks failed"
}

& python tests\backend_llvm_regression_checks.py
if ($LASTEXITCODE -ne 0) {
    throw "LLVM backend regression checks failed"
}

& python tests\backend_mlir_regression_checks.py
if ($LASTEXITCODE -ne 0) {
    throw "MLIR backend regression checks failed"
}

& python tests\backend_selection_regression_checks.py
if ($LASTEXITCODE -ne 0) {
    throw "Backend selection regression checks failed"
}

& python tests\backend_equivalence_regression_checks.py
if ($LASTEXITCODE -ne 0) {
    throw "Backend equivalence regression checks failed"
}

& python tests\target_pipeline_regression_checks.py
if ($LASTEXITCODE -ne 0) {
    throw "Target pipeline regression checks failed"
}

$hostExamples = @(
    "examples\hello.bs",
    "examples\test_io.bs",
    "examples\core_demo.bs",
    "examples\math_demo.bs",
    "examples\arrays_demo.bs",
    "examples\memory_demo.bs",
    "examples\recursion_demo.bs",
    "examples\time_demo.bs",
    "examples\task_demo.bs",
    "examples\strict_demo.bs",
    "examples\bits_demo.bs",
    "examples\crc_demo.bs",
    "examples\ring_demo.bs"
)

foreach ($example in $hostExamples) {
    Invoke-BasisCheck -CommandArgs @("build", $example, "--run")
}

Invoke-BasisCheck `
    -CommandArgs @("build", "examples\callgraph_demo.bs", "--show-resources", "--run") `
    -RequiredText @("callgraph_demo::main -> callgraph_demo::stage_one -> callgraph_demo::stage_two -> callgraph_demo::leaf")

Invoke-BasisCheck `
    -CommandArgs @("build", "examples\effects_demo.bs", "--show-resources", "--emit-c") `
    -RequiredText @("Blocking:      yes", "Allocates:     yes", "Heap (total):        96 bytes")

Invoke-BasisCheck -CommandArgs @("build", "examples\embedded_demo.bs", "--emit-c", "--target", "esp32")
Invoke-BasisCheck `
    -CommandArgs @("build", "examples\time_demo.bs", "--run") `
    -RequiredText @("deadline_reached=false", "before=true")

Invoke-BasisCheck `
    -CommandArgs @("build", "examples\task_demo.bs", "--show-resources", "--emit-c") `
    -RequiredText @("Task:          yes (1024B stack)", "Task Stack Budget: 1024/2048 bytes")

$taskSource = Get-Content .\build\task_demo.c -Raw
if (-not $taskSource.Contains('BASIS_REGION("iram") BASIS_TASK void telemetry_task')) {
    throw "Generated task C does not contain BASIS_REGION/BASIS_TASK task signature."
}

Invoke-BasisCheck `
    -CommandArgs @("build", "examples\storage_demo.bs", "--show-resources", "--emit-c") `
    -RequiredText @("Storage Budget: 512/1024 bytes", "Storage Objects: 4/8")

Invoke-BasisCheck `
    -CommandArgs @("build", "examples\bits_demo.bs", "--run") `
    -RequiredText @("reg=23074", "bit5=true", "aligned=80")

Invoke-BasisCheck `
    -CommandArgs @("build", "examples\crc_demo.bs", "--run") `
    -RequiredText @("crc8=", "crc16=")

Invoke-BasisCheck `
    -CommandArgs @("build", "examples\ring_demo.bs", "--run") `
    -RequiredText @("push1=true", "peek=10", "count_after=1")

Invoke-BasisCheck -CommandArgs @("build", "examples\mmio_demo.bs", "--emit-c", "--target", "esp32")
Invoke-BasisCheck -CommandArgs @("build", "examples\isr_demo.bs", "--lib", "--emit-c", "--target", "esp32")

$isrSource = Get-Content .\build\isr_demo.c -Raw
if (-not $isrSource.Contains("BASIS_INTERRUPT void systick_handler")) {
    throw "Generated ISR C does not contain BASIS_INTERRUPT handler signature."
}

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_while.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_WHILE_REMOVED")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_interrupt_params.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_INTERRUPT_SIGNATURE")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_interrupt_heap.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_INTERRUPT_HEAP")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_ffi_missing_library.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_EXTERN_FFI_LIBRARY_REQUIRED")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_ffi_unverified_library.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_FFI_UNVERIFIED_LIBRARY")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_ffi_unverified_library.bs", "--ffi-policy", "warn", "--emit-c") `
    -ExpectSuccess $true `
    -RequiredText @("W_FFI_UNVERIFIED_LIBRARY")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_ffi_wrapper_required.bs", "--ffi-manifest", "tests\cases\ffi_vendor_manifest.json") `
    -ExpectSuccess $false `
    -RequiredText @("E_FFI_WRAPPER_REQUIRED")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\ffi_unsafe_library.bs", "--ffi-manifest", "tests\cases\ffi_vendor_manifest.json") `
    -ExpectSuccess $false `
    -RequiredText @("E_FFI_UNSAFE_LIBRARY")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\ffi_unsafe_library.bs", "--ffi-manifest", "tests\cases\ffi_vendor_manifest.json", "--ffi-policy", "warn", "--emit-c") `
    -ExpectSuccess $true `
    -RequiredText @("W_FFI_UNSAFE_LIBRARY")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\ffi_wrapped_vendor_ok.bs", "--ffi-manifest", "tests\cases\ffi_vendor_manifest.json", "--emit-c") `
    -ExpectSuccess $true

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_extern_stack.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_EXTERN_STACK_REQUIRED")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_extern_missing_effect.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_EXTERN_EFFECT_REQUIRED")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_extern_effect_conflict.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_EFFECT_CONFLICT")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_extern_allocates_budget.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_EXTERN_ALLOCATES_BUDGET_REQUIRED")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_interrupt_nondeterministic.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_INTERRUPT_NONDETERMINISTIC")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_interrupt_blocking.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_INTERRUPT_BLOCKING")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_interrupt_storage.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_INTERRUPT_STORAGE")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_task_params.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_TASK_SIGNATURE")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_task_return.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_TASK_SIGNATURE")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_task_missing_stack.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_TASK_STACK_REQUIRED")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_task_interrupt_conflict.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_TASK_INTERRUPT_CONFLICT")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_storage_contract.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_STORAGE_CONTRACT_REQUIRED")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_strict_blocking.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_STRICT_BLOCKING")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\invalid_region_expr.bs") `
    -ExpectSuccess $false `
    -RequiredText @("E_INVALID_REGION")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\heuristic_budget_emit_c.bs", "--emit-c") `
    -RequiredText @("Memory Budget:", "Generated C code in")

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\heuristic_budget_emit_c.bs") `
    -RequiredText @("Memory Budget:", "Built executable:")

$budgetOutput = (& cmd /c "python compiler\basis.py build tests\cases\exact_code_budget_fail.bs --emit-c 2>&1" | Out-String)
$budgetExit = $LASTEXITCODE
if ($budgetExit -eq 0) {
    throw "Command unexpectedly succeeded: python compiler\basis.py build tests\cases\exact_code_budget_fail.bs --emit-c`n$budgetOutput"
}
if (-not $budgetOutput.Contains("ERROR: Program exceeds declared memory budget!")) {
    throw "Expected exact code budget failure output to contain the budget error.`n$budgetOutput"
}

Invoke-BasisCheck `
    -CommandArgs @("build", "tests\cases\heuristic_budget_emit_c.bs", "--emit-c", "--target-config", "tests\cases\tiny_flash_target.json") `
    -RequiredText @("Code:  not validated (target artifact size unavailable)")

if ($VerifyPackage) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 -Clean -Package
    if ($LASTEXITCODE -ne 0) {
        throw "Release package build failed."
    }

    $version = (Get-Content .\VERSION.txt -Raw).Trim()
    $zipPath = ".\BASIS-v$version-win64.zip"

    foreach ($path in @(
        ".\dist\bin\basis.exe",
        ".\dist\basis.bat",
        ".\dist\README.md",
        ".\dist\docs\LEARN.md",
        ".\dist\stdlib\bits\bits.bs",
        ".\dist\stdlib\crc\crc.bs",
        ".\dist\stdlib\ring\ring.bs",
        $zipPath
    )) {
        if (-not (Test-Path $path)) {
            throw "Expected package artifact missing: $path"
        }
    }

    Push-Location .\dist
    try {
        $packageOutput = (& .\basis.bat build examples\bits_demo.bs --emit-c 2>&1 | Out-String)
        $packageExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    if ($packageExit -ne 0) {
        throw "Packaged compiler failed to build examples\bits_demo.bs`n$packageOutput"
    }

    if (-not (Test-Path .\dist\build\bits_demo.c)) {
        throw "Packaged compiler did not emit dist\build\bits_demo.c"
    }
}

Write-Host "All BASIS local checks passed."
