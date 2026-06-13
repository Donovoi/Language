param(
    [ValidateSet("all", "source-bundle", "gateway-package")]
    [string]$Action = "all",
    [string]$Python = $(if ($env:PYTHON) { $env:PYTHON } else { "python" }),
    [string]$Version = "",
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

function Resolve-Executable {
    param([string]$Candidate, [string]$Label)

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
        throw "$Label uses Python $version, but the gateway packaging path supports >=3.11,<3.14. Pass -Python pointing at a supported interpreter."
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

function Invoke-GitCommand {
    param(
        [string]$Label,
        [string]$RepoRoot,
        [string[]]$Arguments
    )

    $gitArguments = @("-c", "safe.directory=$RepoRoot", "-C", $RepoRoot) + $Arguments
    Invoke-CheckedCommand `
        -Label $Label `
        -FilePath "git" `
        -Arguments $gitArguments `
        -WorkingDirectory $RepoRoot
}

function Get-ReleaseVersion {
    param([string]$RepoRoot, [string]$OverrideVersion)

    if (-not [string]::IsNullOrWhiteSpace($OverrideVersion)) {
        return $OverrideVersion
    }

    $pubspecPath = Join-Path $RepoRoot "apps\field_app_flutter\pubspec.yaml"
    foreach ($line in Get-Content -LiteralPath $pubspecPath) {
        if ($line -match "^version:\s*([^\+\s]+)") {
            return $Matches[1]
        }
    }

    throw "Could not determine release version from apps/field_app_flutter/pubspec.yaml."
}

function Assert-CleanGitTree {
    param([string]$RepoRoot, [bool]$AllowDirtyTree)

    if ($AllowDirtyTree) {
        Write-Host "Proceeding with a dirty tree because -AllowDirty was supplied."
        return
    }

    $status = & git -c "safe.directory=$RepoRoot" -C $RepoRoot status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect git status."
    }
    if ($status) {
        throw "Refusing to build release artifacts from a dirty tree. Commit/stash changes or pass -AllowDirty for a deliberate local test artifact."
    }
}

function Build-SourceBundle {
    param([string]$RepoRoot, [string]$ReleaseVersion)

    $distDir = Join-Path $RepoRoot "dist"
    New-Item -ItemType Directory -Path $distDir -Force | Out-Null

    $tarPath = Join-Path $distDir "language-$ReleaseVersion-source.tar.gz"
    $zipPath = Join-Path $distDir "language-$ReleaseVersion-source.zip"

    Invoke-GitCommand `
        -Label "source bundle tar.gz" `
        -RepoRoot $RepoRoot `
        -Arguments @("archive", "--format=tar.gz", "--output=$tarPath", "HEAD")
    Invoke-GitCommand `
        -Label "source bundle zip" `
        -RepoRoot $RepoRoot `
        -Arguments @("archive", "--format=zip", "--output=$zipPath", "HEAD")

    Write-Host "Wrote $tarPath"
    Write-Host "Wrote $zipPath"
}

function Build-GatewayPackage {
    param([string]$RepoRoot, [string]$PythonPath)

    $gatewayDir = Join-Path $RepoRoot "services\gateway"
    $distDir = Join-Path $gatewayDir "dist"
    Remove-Item -LiteralPath $distDir -Recurse -Force -ErrorAction SilentlyContinue

    Invoke-CheckedCommand `
        -Label "create gateway virtualenv" `
        -FilePath $PythonPath `
        -Arguments @("-m", "venv", "--clear", ".venv") `
        -WorkingDirectory $gatewayDir

    $gatewayPython = Join-Path $gatewayDir ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $gatewayPython -PathType Leaf)) {
        $gatewayPython = Join-Path $gatewayDir ".venv/bin/python"
    }
    if (-not (Test-Path -LiteralPath $gatewayPython -PathType Leaf)) {
        throw "Gateway virtualenv Python was not created."
    }
    $gatewayPython = (Resolve-Path -LiteralPath $gatewayPython).Path
    Assert-SupportedPython -FilePath $gatewayPython -Label "Gateway Python"

    Invoke-CheckedCommand `
        -Label "upgrade gateway pip" `
        -FilePath $gatewayPython `
        -Arguments @("-m", "pip", "install", "--upgrade", "pip") `
        -WorkingDirectory $gatewayDir
    Invoke-CheckedCommand `
        -Label "install gateway build dependencies" `
        -FilePath $gatewayPython `
        -Arguments @("-m", "pip", "install", "build") `
        -WorkingDirectory $gatewayDir
    Invoke-CheckedCommand `
        -Label "install gateway dev package" `
        -FilePath $gatewayPython `
        -Arguments @("-m", "pip", "install", "-e", ".[dev]") `
        -WorkingDirectory $gatewayDir
    Invoke-CheckedCommand `
        -Label "build gateway distributions" `
        -FilePath $gatewayPython `
        -Arguments @("-m", "build") `
        -WorkingDirectory $gatewayDir

    $sdists = @(Get-ChildItem -LiteralPath $distDir -Filter "*.tar.gz")
    $wheels = @(Get-ChildItem -LiteralPath $distDir -Filter "*.whl")
    if ($sdists.Count -ne 1) {
        throw "Expected exactly one gateway sdist in $distDir, found $($sdists.Count)."
    }
    if ($wheels.Count -ne 1) {
        throw "Expected exactly one gateway wheel in $distDir, found $($wheels.Count)."
    }

    Write-Host "Wrote $($sdists[0].FullName)"
    Write-Host "Wrote $($wheels[0].FullName)"
}

$repoRoot = Resolve-RepoRoot
$pythonPath = $null
if ($Action -eq "all" -or $Action -eq "gateway-package") {
    $pythonPath = Resolve-Executable -Candidate $Python -Label "Python"
    Assert-SupportedPython -FilePath $pythonPath -Label "Python"
}
$releaseVersion = Get-ReleaseVersion -RepoRoot $repoRoot -OverrideVersion $Version
Assert-CleanGitTree -RepoRoot $repoRoot -AllowDirtyTree $AllowDirty.IsPresent

if ($Action -eq "all" -or $Action -eq "source-bundle") {
    Build-SourceBundle -RepoRoot $repoRoot -ReleaseVersion $releaseVersion
}

if ($Action -eq "all" -or $Action -eq "gateway-package") {
    Build-GatewayPackage -RepoRoot $repoRoot -PythonPath $pythonPath
}

Write-Host ""
Write-Host "Local package build passed."
