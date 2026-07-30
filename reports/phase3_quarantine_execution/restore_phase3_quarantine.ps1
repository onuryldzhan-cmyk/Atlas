$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

$Source = Join-Path $ProjectRoot "_quarantine\phase3\execution_manager.py"
$Destination = Join-Path $ProjectRoot "execution_manager.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\ai\core\atlas_brain_backup_v6.py"
$Destination = Join-Path $ProjectRoot "ai\core\atlas_brain_backup_v6.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\ai\core\atlas_brain_old_v8.py"
$Destination = Join-Path $ProjectRoot "ai\core\atlas_brain_old_v8.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\core\decision_adapter_backup.py"
$Destination = Join-Path $ProjectRoot "core\decision_adapter_backup.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\core\execution_manager_backup.py"
$Destination = Join-Path $ProjectRoot "core\execution_manager_backup.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\core\execution_manager_v1_backup.py"
$Destination = Join-Path $ProjectRoot "core\execution_manager_v1_backup.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\core\execution_manager_v28_backup.py"
$Destination = Join-Path $ProjectRoot "core\execution_manager_v28_backup.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\core\execution_manager_v7_backup.py"
$Destination = Join-Path $ProjectRoot "core\execution_manager_v7_backup.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\core\execution_manager_v9_backup.py"
$Destination = Join-Path $ProjectRoot "core\execution_manager_v9_backup.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\core\execution_models_v21_backup.py"
$Destination = Join-Path $ProjectRoot "core\execution_models_v21_backup.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\core\execution_state_v1_backup.py"
$Destination = Join-Path $ProjectRoot "core\execution_state_v1_backup.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\intelligence\core\intelligence_core_backup.py"
$Destination = Join-Path $ProjectRoot "intelligence\core\intelligence_core_backup.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\phase1_backup_20260727_132959\atlas_os\__init__.py"
$Destination = Join-Path $ProjectRoot "phase1_backup_20260727_132959\atlas_os\__init__.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

$Source = Join-Path $ProjectRoot "_quarantine\phase3\phase1_backup_20260727_133009\atlas_os\__init__.py"
$Destination = Join-Path $ProjectRoot "phase1_backup_20260727_133009\atlas_os\__init__.py"

if (Test-Path $Source) {
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Move-Item -Path $Source -Destination $Destination -Force
    Write-Host "Restored: $Destination"
} else {
    Write-Host "Skipped missing quarantine file: $Source"
}

Write-Host "Phase 3 quarantine restore completed."