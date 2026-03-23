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

    $output = (& python compiler\basis.py @CommandArgs 2>&1 | Out-String)
    $exitCode = $LASTEXITCODE

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
    compiler\basis.py `
    compiler\parser.py `
    compiler\sema.py `
    compiler\loop_analysis.py `
    compiler\resource_analysis.py `
    compiler\codegen.py `
    compiler\module_codegen.py

if ($LASTEXITCODE -ne 0) {
    throw "python -m py_compile failed"
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
    "examples\strict_demo.bs"
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

Write-Host "All BASIS local checks passed."
