# BASIS build script
# Creates a versioned distributable package with the compiler executable

param(
    [switch]$Clean,
    [switch]$BuildExe,
    [switch]$Package
)

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot
$DIST = "$ROOT\dist"
$BUILDDIR = "$ROOT\build_temp"
$VERSION = (Get-Content "$ROOT\VERSION.txt" -Raw).Trim()

function Clean-Build {
    Write-Host "Cleaning build artifacts..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $DIST -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $BUILDDIR -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ROOT\compiler\dist" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ROOT\compiler\build" -ErrorAction SilentlyContinue
    Remove-Item -Force "$ROOT\compiler\*.spec" -ErrorAction SilentlyContinue
    Write-Host "Clean complete." -ForegroundColor Green
}

function Build-Executable {
    Write-Host "Building BASIS compiler executable v$VERSION..." -ForegroundColor Yellow
    
    Push-Location "$ROOT\compiler"
    
    # Build single-file executable using python -m
    python -m PyInstaller --onefile `
        --name basis `
        --distpath "$DIST\bin" `
        --workpath "$BUILDDIR" `
        --specpath "$BUILDDIR" `
        --clean `
        basis.py
    
    Pop-Location
    
    if (Test-Path "$DIST\bin\basis.exe") {
        Write-Host "Executable built: $DIST\bin\basis.exe" -ForegroundColor Green
    } else {
        Write-Error "Build failed!"
    }
}

function Create-Package {
    Write-Host "Creating distribution package v$VERSION..." -ForegroundColor Yellow
    
    # Create directory structure
    New-Item -ItemType Directory -Force -Path "$DIST\stdlib" | Out-Null
    New-Item -ItemType Directory -Force -Path "$DIST\examples" | Out-Null
    New-Item -ItemType Directory -Force -Path "$DIST\docs" | Out-Null
    
    # Copy stdlib (avoiding nested copies)
    Get-ChildItem "$ROOT\stdlib" -Directory | ForEach-Object {
        if ($_.Name -ne "stdlib") {
            Copy-Item -Recurse -Force $_.FullName "$DIST\stdlib\"
        }
    }
    
    # Copy examples (avoiding nested copies)
    Get-ChildItem "$ROOT\examples\*.bs" -File | Copy-Item -Destination "$DIST\examples\" -Force
    
    # Copy documentation
    Copy-Item -Force "$ROOT\README.md" "$DIST\"
    Copy-Item -Force "$ROOT\LEARN.md" "$DIST\docs\"
    Copy-Item -Force "$ROOT\VERSION.txt" "$DIST\"
    Copy-Item -Force "$ROOT\compiler\README.md" "$DIST\docs\"
    Copy-Item -Force "$ROOT\compiler\syntax.md" "$DIST\docs\"
    Copy-Item -Force "$ROOT\compiler\safeguards.md" "$DIST\docs\"
    Copy-Item -Force "$ROOT\compiler\limitations.md" "$DIST\docs\"
    
    # Create version file
    @"
BASIS Language Compiler v$VERSION
Built: $(Get-Date -Format "yyyy-MM-dd")

A deterministic, resource-aware systems language for embedded development.

Usage:
  basis build <file.bs> [--run]

Example:
  basis build examples\hello.bs --run

Documentation:
  See README.md and docs\ folder for language reference.
"@ | Set-Content "$DIST\README.txt"
    
    # Create batch wrapper for easier use
    @"
@echo off
"%~dp0bin\basis.exe" %*
"@ | Set-Content "$DIST\basis.bat"
    
    Write-Host "Package created at: $DIST" -ForegroundColor Green
    
    # Show contents
    Write-Host "`nPackage contents:" -ForegroundColor Cyan
    Get-ChildItem $DIST -Recurse -File | ForEach-Object {
        Write-Host "  $($_.FullName.Replace($DIST, '.'))"
    }
    
    # Create ZIP archive
    $zipPath = "$ROOT\BASIS-v$VERSION-win64.zip"
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
    Compress-Archive -Path "$DIST\*" -DestinationPath $zipPath
    $zipSize = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
    Write-Host "`nZIP archive created: $zipPath ($zipSize MB)" -ForegroundColor Green
}

# Main
if ($Clean -or (-not $BuildExe -and -not $Package)) {
    Clean-Build
}

if ($BuildExe -or (-not $Clean -and -not $Package)) {
    Build-Executable
}

if ($Package) {
    if (-not (Test-Path "$DIST\bin\basis.exe")) {
        Build-Executable
    }
    Create-Package
}

Write-Host "`nDone!" -ForegroundColor Green
