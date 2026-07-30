[CmdletBinding()]
param(
    [ValidateSet('Setup','Validate','Core','Dashboard','Package')]
    [string]$Action = 'Validate'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
Set-Location -LiteralPath $projectRoot

function Get-AtlasPython {
    if (Test-Path -LiteralPath $venvPython) { return $venvPython }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) { throw 'Python 3.11+ bulunamadı. python.org üzerinden Python kurun.' }
    & $launcher.Source -3 -m venv .venv
    return $venvPython
}

function Install-Atlas {
    $python = Get-AtlasPython
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements/dev.txt
}

function Test-Atlas {
    $python = Get-AtlasPython
    & $python -m compileall -q core atlas_os atlas_runtime atlas_finance intelligence assistant ai main.py web_app.py
    if ($LASTEXITCODE -ne 0) { throw 'Python derleme kontrolü başarısız.' }
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Test paketi başarısız.' }
    Write-Host 'Atlas validation gate: PASS' -ForegroundColor Green
}

switch ($Action) {
    'Setup' { Install-Atlas; Copy-Item .env.example .env -ErrorAction SilentlyContinue; Test-Atlas }
    'Validate' { Test-Atlas }
    'Core' { $python = Get-AtlasPython; & $python main.py }
    'Dashboard' { $python = Get-AtlasPython; & $python -m uvicorn web_app:app --host 127.0.0.1 --port 8000 }
    'Package' {
        Test-Atlas
        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $destination = Join-Path (Split-Path $projectRoot -Parent) "Atlas_AI_$stamp.zip"
        Compress-Archive -Path (Join-Path $projectRoot '*') -DestinationPath $destination -CompressionLevel Optimal
        Write-Host "Paket: $destination" -ForegroundColor Cyan
    }
}
