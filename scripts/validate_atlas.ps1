[CmdletBinding()]
param(
    [switch]$KeepEnvironment,
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (
    Resolve-Path (
        Join-Path $PSScriptRoot ".."
    )
).Path

$VenvPath = Join-Path $RepoRoot ".venv_atlas_validation"

$ValidationPython = Join-Path `
    $VenvPath `
    "Scripts\python.exe"

$TempParent = "C:\Atlas_Validation_Temp"

$TempRoot = Join-Path `
    $TempParent `
    ("pytest-" + [guid]::NewGuid().ToString("N"))

$ScriptExitCode = 0


function Write-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host ""
    Write-Host "========================================"
    Write-Host $Message
    Write-Host "========================================"
}


function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Executable @Arguments

    $CommandExitCode = $LASTEXITCODE

    if ($CommandExitCode -ne 0) {
        $RenderedCommand = (
            $Executable + " " + ($Arguments -join " ")
        )

        throw (
            "Command failed with exit code {0}: {1}" -f `
                $CommandExitCode, `
                $RenderedCommand
        )
    }
}


try {
    Set-Location $RepoRoot

    Write-Step "ATLAS VALIDATION - REPOSITORY"

    Write-Host "Repository:"
    Write-Host $RepoRoot

    Write-Host ""
    Write-Host "Branch:"

    Invoke-Checked `
        -Executable "git" `
        -Arguments @(
            "branch",
            "--show-current"
        )

    Write-Host ""
    Write-Host "HEAD:"

    Invoke-Checked `
        -Executable "git" `
        -Arguments @(
            "rev-parse",
            "HEAD"
        )

    Write-Host ""
    Write-Host "Working tree:"

    $GitStatus = & git status --short

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read Git working-tree status."
    }

    if ($GitStatus) {
        $GitStatus | ForEach-Object {
            Write-Host $_
        }
    }
    else {
        Write-Host "CLEAN"
    }


    Write-Step "ATLAS VALIDATION - CLEAN ISOLATED ENVIRONMENT"

    if (Test-Path $VenvPath) {
        Remove-Item `
            $VenvPath `
            -Recurse `
            -Force
    }

    Invoke-Checked `
        -Executable "python" `
        -Arguments @(
            "-m",
            "venv",
            $VenvPath
        )

    if (-not (Test-Path $ValidationPython)) {
        throw (
            "Validation Python executable was not created: " +
            $ValidationPython
        )
    }

    Write-Host "Virtual environment created:"
    Write-Host $VenvPath


    Write-Step "ATLAS VALIDATION - RUNTIME DEPENDENCIES"

    Invoke-Checked `
        -Executable $ValidationPython `
        -Arguments @(
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-c",
            "requirements/constraints.txt",
            "-r",
            "requirements.txt"
        )


    Write-Step "ATLAS VALIDATION - DEVELOPMENT DEPENDENCIES"

    Invoke-Checked `
        -Executable $ValidationPython `
        -Arguments @(
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-c",
            "requirements/constraints.txt",
            "-r",
            "requirements/dev.txt"
        )


    Write-Step "ATLAS VALIDATION - DEPENDENCY INTEGRITY"

    Invoke-Checked `
        -Executable $ValidationPython `
        -Arguments @(
            "-m",
            "pip",
            "check"
        )


    if (-not $SkipTests) {

        Write-Step "ATLAS VALIDATION - TEST TEMP DIRECTORY"

        if (-not (Test-Path $TempParent)) {
            New-Item `
                -ItemType Directory `
                -Path $TempParent `
                -Force |
                Out-Null
        }

        New-Item `
            -ItemType Directory `
            -Path $TempRoot `
            -Force |
            Out-Null

        Write-Host "Pytest basetemp:"
        Write-Host $TempRoot


        Write-Step "ATLAS VALIDATION - TEST SUITE"

        Invoke-Checked `
            -Executable $ValidationPython `
            -Arguments @(
                "-m",
                "pytest",
                "-q",
                "--basetemp=$TempRoot"
            )
    }
    else {
        Write-Step "ATLAS VALIDATION - TEST SUITE"

        Write-Host "SKIPPED by explicit -SkipTests request."
    }


    Write-Step "ATLAS VALIDATION - FINAL RESULT"

    Write-Host "STATUS: PASS" `
        -ForegroundColor Green

    Write-Host "Dependency isolation: PASS"
    Write-Host "pip check: PASS"

    if ($SkipTests) {
        Write-Host "Test suite: SKIPPED"
    }
    else {
        Write-Host "Test suite: PASS"
    }

    Write-Host ""
    Write-Host "Canonical validation interpreter:"
    Write-Host $ValidationPython

    Write-Host ""
    Write-Host (
        "The user's global Python environment was not used " +
        "as dependency-validation authority."
    )
}
catch {
    $ScriptExitCode = 1

    Write-Host ""
    Write-Host "========================================"
    Write-Host "ATLAS VALIDATION - FINAL RESULT"
    Write-Host "========================================"

    Write-Host "STATUS: FAIL" `
        -ForegroundColor Red

    Write-Host ""
    Write-Host "Reason:"
    Write-Host $_.Exception.Message `
        -ForegroundColor Red
}
finally {

    Write-Step "ATLAS VALIDATION - CLEANUP"

    if (Test-Path $TempRoot) {
        try {
            Remove-Item `
                $TempRoot `
                -Recurse `
                -Force `
                -ErrorAction Stop

            Write-Host "Temporary pytest directory removed."
        }
        catch {
            Write-Warning (
                "Unable to remove pytest temp directory: " +
                $TempRoot
            )
        }
    }

    if (
        (Test-Path $TempParent) -and
        -not (
            Get-ChildItem `
                $TempParent `
                -Force `
                -ErrorAction SilentlyContinue
        )
    ) {
        Remove-Item `
            $TempParent `
            -Force `
            -ErrorAction SilentlyContinue
    }

    if ($KeepEnvironment) {
        if (Test-Path $VenvPath) {
            Write-Host "Validation environment preserved:"
            Write-Host $VenvPath
        }
    }
    else {
        if (Test-Path $VenvPath) {
            try {
                Remove-Item `
                    $VenvPath `
                    -Recurse `
                    -Force `
                    -ErrorAction Stop

                Write-Host "Validation virtual environment removed."
            }
            catch {
                Write-Warning (
                    "Unable to remove validation environment: " +
                    $VenvPath
                )
            }
        }
    }

    Set-Location $RepoRoot
}

exit $ScriptExitCode
