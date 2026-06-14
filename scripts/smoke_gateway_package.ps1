param(
    [string]$WheelPath = "",
    [string]$Python = "",
    [int]$GatewayPort = $(if ($env:GATEWAY_PACKAGE_SMOKE_PORT) { [int]$env:GATEWAY_PACKAGE_SMOKE_PORT } else { 8011 }),
    [switch]$KeepTemp
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

function Get-PythonSupportError {
    param([string]$FilePath, [string]$Label)

    $version = Get-PythonVersion -FilePath $FilePath -Label $Label
    if ($version.Major -ne 3 -or $version.Minor -lt 11 -or $version.Minor -ge 14) {
        return "$Label uses Python $version, but the package smoke path supports >=3.11,<3.14."
    }
    return ""
}

function Get-PythonCandidates {
    param([string]$RequestedPython)

    $candidates = New-Object System.Collections.Generic.List[object]
    if (-not [string]::IsNullOrWhiteSpace($RequestedPython)) {
        $candidates.Add([pscustomobject]@{ Label = "Python argument"; Candidate = $RequestedPython })
        return $candidates.ToArray()
    }
    foreach ($name in @("LANGUAGE_PACKAGE_PYTHON", "LANGUAGE_PYTHON", "PYTHON")) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $candidates.Add([pscustomobject]@{ Label = $name; Candidate = $value })
        }
    }
    $codexRuntimePython = Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $codexRuntimePython -PathType Leaf) {
        $candidates.Add([pscustomobject]@{ Label = "Codex bundled Python"; Candidate = $codexRuntimePython })
    }
    $candidates.Add([pscustomobject]@{ Label = "PATH python"; Candidate = "python" })
    return $candidates.ToArray()
}

function Resolve-SupportedPython {
    param([string]$RequestedPython)

    $errors = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in Get-PythonCandidates -RequestedPython $RequestedPython) {
        try {
            $candidatePath = Resolve-Executable -Candidate $candidate.Candidate -Label $candidate.Label
            $supportError = Get-PythonSupportError -FilePath $candidatePath -Label $candidate.Label
            if (-not $supportError) {
                Write-Host "Using $($candidate.Label): $candidatePath"
                return $candidatePath
            }
            $errors.Add($supportError)
        } catch {
            $errors.Add("$($candidate.Label): $($_.Exception.Message)")
        }
    }
    throw "Could not find a supported Python >=3.11,<3.14 for package smoke. $($errors -join ' ')"
}

function Resolve-GatewayWheel {
    param([string]$RepoRoot, [string]$RequestedWheel)

    if (-not [string]::IsNullOrWhiteSpace($RequestedWheel)) {
        if (-not (Test-Path -LiteralPath $RequestedWheel -PathType Leaf)) {
            throw "Gateway wheel was not found: $RequestedWheel"
        }
        return (Resolve-Path -LiteralPath $RequestedWheel).Path
    }

    $artifactDir = Join-Path $RepoRoot "dist\local-release-artifacts"
    $wheels = @(Get-ChildItem -LiteralPath $artifactDir -Filter "language_gateway-*.whl" -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc -Descending)
    if ($wheels.Count -ne 1) {
        throw "Expected exactly one language_gateway wheel in $artifactDir, found $($wheels.Count). Run release-artifacts first."
    }
    return $wheels[0].FullName
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

$repoRoot = Resolve-RepoRoot
$pythonPath = Resolve-SupportedPython -RequestedPython $Python
$wheel = Resolve-GatewayWheel -RepoRoot $repoRoot -RequestedWheel $WheelPath
$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("language-gateway-package-smoke-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

try {
    Invoke-CheckedCommand `
        -Label "create package smoke virtualenv" `
        -FilePath $pythonPath `
        -Arguments @("-m", "venv", "--clear", ".venv") `
        -WorkingDirectory $tmpDir

    $venvPython = Join-Path $tmpDir ".venv\Scripts\python.exe"
    $gatewayCommand = Join-Path $tmpDir ".venv\Scripts\language-gateway.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $venvPython = Join-Path $tmpDir ".venv/bin/python"
        $gatewayCommand = Join-Path $tmpDir ".venv/bin/language-gateway"
    }
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "Package smoke virtualenv Python was not created."
    }

    Invoke-CheckedCommand `
        -Label "install gateway wheel into package smoke virtualenv" `
        -FilePath $venvPython `
        -Arguments @("-m", "pip", "install", "--disable-pip-version-check", $wheel) `
        -WorkingDirectory $tmpDir

    if (-not (Test-Path -LiteralPath $gatewayCommand -PathType Leaf)) {
        throw "Installed language-gateway command was not created: $gatewayCommand"
    }

    Invoke-CheckedCommand `
        -Label "smoke installed gateway command" `
        -FilePath "pwsh" `
        -Arguments @(
            "-NoProfile",
            "-File",
            (Join-Path $repoRoot "scripts\smoke_local_demo.ps1"),
            "-GatewayCommand",
            $gatewayCommand,
            "-GatewayWorkingDirectory",
            $tmpDir,
            "-GatewayPort",
            "$GatewayPort",
            "-RequireStartedGateway"
        ) `
        -WorkingDirectory $tmpDir

    Write-Host "Packaged gateway smoke check passed"
} finally {
    if ($KeepTemp.IsPresent) {
        Write-Host "Keeping package smoke temp directory: $tmpDir"
    } else {
        Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
