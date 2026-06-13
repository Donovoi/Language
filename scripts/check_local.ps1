param(
    [string]$Python = $(if ($env:PYTHON) { $env:PYTHON } else { "python" }),
    [string]$GatewayPython = $(if ($env:GATEWAY_PYTHON) { $env:GATEWAY_PYTHON } else { "" }),
    [string]$Flutter = $(if ($env:FLUTTER) { $env:FLUTTER } else { "flutter" }),
    [switch]$UseExistingGatewayVenv,
    [switch]$SkipFlutter
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

function Resolve-Executable {
    param([string]$Candidate, [string]$Label)

    if ([string]::IsNullOrWhiteSpace($Candidate)) {
        throw "$Label executable was not provided."
    }

    if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
        return (Resolve-Path -LiteralPath $Candidate).Path
    }

    $command = Get-Command $Candidate -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    throw "$Label executable '$Candidate' was not found on PATH."
}

function Get-PythonVersion {
    param([string]$FilePath, [string]$Label)

    $versionText = & $FilePath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect $Label version."
    }
    return [Version]($versionText | Select-Object -First 1)
}

function Assert-SupportedPython {
    param([string]$FilePath, [string]$Label)

    $version = Get-PythonVersion -FilePath $FilePath -Label $Label
    if ($version.Major -ne 3 -or $version.Minor -lt 11 -or $version.Minor -ge 14) {
        throw "$Label uses Python $version, but the gateway supports >=3.11,<3.14. Pass -Python pointing at a supported interpreter."
    }
}

function Invoke-CheckedCommand {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )

    Write-Host ""
    Write-Host "==> $Label"
    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Label failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
}

function Resolve-GatewayPython {
    param([string]$RepoRoot, [string]$Candidate)

    if (-not [string]::IsNullOrWhiteSpace($Candidate)) {
        return Resolve-Executable -Candidate $Candidate -Label "Gateway Python"
    }

    $windowsVenv = Join-Path $RepoRoot "services\gateway\.venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $windowsVenv -PathType Leaf) {
        return (Resolve-Path -LiteralPath $windowsVenv).Path
    }

    $posixVenv = Join-Path $RepoRoot "services/gateway/.venv/bin/python"
    if (Test-Path -LiteralPath $posixVenv -PathType Leaf) {
        return (Resolve-Path -LiteralPath $posixVenv).Path
    }

    throw "Gateway Python was not found under services/gateway/.venv. Omit -UseExistingGatewayVenv to refresh the local venv, or pass -GatewayPython."
}

$repoRoot = Resolve-RepoRoot
$gatewayDir = Join-Path $repoRoot "services\gateway"
$flutterDir = Join-Path $repoRoot "apps\field_app_flutter"
$pythonPath = Resolve-Executable -Candidate $Python -Label "Python"
Assert-SupportedPython -FilePath $pythonPath -Label "Python"

if ($UseExistingGatewayVenv) {
    $gatewayPython = Resolve-GatewayPython -RepoRoot $repoRoot -Candidate $GatewayPython
    Assert-SupportedPython -FilePath $gatewayPython -Label "Gateway Python"
} else {
    Invoke-CheckedCommand `
        -Label "create gateway virtualenv" `
        -FilePath $pythonPath `
        -Arguments @("-m", "venv", "--clear", ".venv") `
        -WorkingDirectory $gatewayDir

    $gatewayPython = Resolve-GatewayPython -RepoRoot $repoRoot -Candidate ""
    Assert-SupportedPython -FilePath $gatewayPython -Label "Gateway Python"
    Invoke-CheckedCommand `
        -Label "upgrade gateway pip" `
        -FilePath $gatewayPython `
        -Arguments @("-m", "pip", "install", "--upgrade", "pip") `
        -WorkingDirectory $gatewayDir
    Invoke-CheckedCommand `
        -Label "install gateway dev package" `
        -FilePath $gatewayPython `
        -Arguments @("-m", "pip", "install", "-e", ".[dev]") `
        -WorkingDirectory $gatewayDir
}

Invoke-CheckedCommand `
    -Label "contract-bindings-check" `
    -FilePath $pythonPath `
    -Arguments @("scripts\generate_contract_bindings.py", "--check") `
    -WorkingDirectory $repoRoot

Invoke-CheckedCommand `
    -Label "research-pack-check" `
    -FilePath $pythonPath `
    -Arguments @("scripts\prepare_robin_research_pack.py", "--check") `
    -WorkingDirectory $repoRoot

Invoke-CheckedCommand `
    -Label "audio-corpus-catalog-check" `
    -FilePath $pythonPath `
    -Arguments @("scripts\check_audio_corpus_catalog.py") `
    -WorkingDirectory $repoRoot

$cargoPath = Resolve-Executable -Candidate "cargo" -Label "Cargo"
Invoke-CheckedCommand `
    -Label "cargo fmt --all --check" `
    -FilePath $cargoPath `
    -Arguments @("fmt", "--all", "--check") `
    -WorkingDirectory $repoRoot
Invoke-CheckedCommand `
    -Label "cargo clippy --workspace --all-targets --all-features -- -D warnings" `
    -FilePath $cargoPath `
    -Arguments @("clippy", "--workspace", "--all-targets", "--all-features", "--", "-D", "warnings") `
    -WorkingDirectory $repoRoot
Invoke-CheckedCommand `
    -Label "cargo test --workspace" `
    -FilePath $cargoPath `
    -Arguments @("test", "--workspace") `
    -WorkingDirectory $repoRoot

Invoke-CheckedCommand `
    -Label "gateway ruff" `
    -FilePath $gatewayPython `
    -Arguments @("-m", "ruff", "check", ".") `
    -WorkingDirectory $gatewayDir
Invoke-CheckedCommand `
    -Label "gateway pytest" `
    -FilePath $gatewayPython `
    -Arguments @("-m", "pytest") `
    -WorkingDirectory $gatewayDir

if ($SkipFlutter) {
    Write-Host ""
    Write-Host "==> flutter-check skipped by -SkipFlutter"
    Write-Host "This was a partial host validation run, not a full replacement for make check."
} else {
    $flutterPath = Resolve-Executable -Candidate $Flutter -Label "Flutter"
    Invoke-CheckedCommand `
        -Label "flutter create" `
        -FilePath $flutterPath `
        -Arguments @("create", ".", "--platforms=android,ios,macos,windows") `
        -WorkingDirectory $flutterDir
    Remove-Item -LiteralPath (Join-Path $flutterDir "test\widget_test.dart") -Force -ErrorAction SilentlyContinue
    Invoke-CheckedCommand `
        -Label "flutter pub get" `
        -FilePath $flutterPath `
        -Arguments @("pub", "get") `
        -WorkingDirectory $flutterDir
    Invoke-CheckedCommand `
        -Label "flutter analyze" `
        -FilePath $flutterPath `
        -Arguments @("analyze") `
        -WorkingDirectory $flutterDir
    Invoke-CheckedCommand `
        -Label "flutter test" `
        -FilePath $flutterPath `
        -Arguments @("test") `
        -WorkingDirectory $flutterDir
}

Write-Host ""
if ($SkipFlutter) {
    Write-Host "Partial local repository validation passed; Flutter was skipped."
} else {
    Write-Host "Local repository validation passed."
}
