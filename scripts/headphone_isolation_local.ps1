param(
    [Parameter(Position = 0)]
    [ValidateSet("self-test", "list-devices", "preflight", "sweep-routes", "probe-route", "virtual-lab", "prepare-manual", "collect-headphone-evidence", "check-manual", "play-manual", "import-manual", "score-manual", "capture", "score")]
    [string]$Action = "self-test",
    [string]$Python = "",
    [string]$Venv = "",
    [switch]$RecreateVenv,
    [switch]$SkipDependencyInstall,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs
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

    $errorMessage = Get-PythonSupportError -FilePath $FilePath -Label $Label
    if ($errorMessage) {
        throw $errorMessage
    }
}

function Get-PythonSupportError {
    param([string]$FilePath, [string]$Label)

    $version = Get-PythonVersion -FilePath $FilePath -Label $Label
    if ($version.Major -ne 3 -or $version.Minor -lt 11 -or $version.Minor -ge 14) {
        return "$Label uses Python $version, but the local audio evidence path supports >=3.11,<3.14. Pass -Python or set LANGUAGE_PYTHON to a supported interpreter."
    }
    return ""
}

function Get-PythonCandidates {
    param([string]$RequestedPython, [string]$RepoRoot)

    $candidates = New-Object System.Collections.Generic.List[object]
    if (-not [string]::IsNullOrWhiteSpace($RequestedPython)) {
        $candidates.Add([pscustomobject]@{ Label = "Python argument"; Candidate = $RequestedPython })
        return $candidates.ToArray()
    }

    if (-not [string]::IsNullOrWhiteSpace($env:LANGUAGE_PYTHON)) {
        $candidates.Add([pscustomobject]@{ Label = "LANGUAGE_PYTHON"; Candidate = $env:LANGUAGE_PYTHON })
    }
    if (-not [string]::IsNullOrWhiteSpace($env:PYTHON)) {
        $candidates.Add([pscustomobject]@{ Label = "PYTHON"; Candidate = $env:PYTHON })
    }

    $codexRuntimePython = Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $codexRuntimePython -PathType Leaf) {
        $candidates.Add([pscustomobject]@{ Label = "Codex bundled Python"; Candidate = $codexRuntimePython })
    }

    $candidates.Add([pscustomobject]@{ Label = "PATH python"; Candidate = "python" })
    return $candidates.ToArray()
}

function Resolve-SupportedPython {
    param([string]$RequestedPython, [string]$RepoRoot)

    $errors = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in Get-PythonCandidates -RequestedPython $RequestedPython -RepoRoot $RepoRoot) {
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

    $details = $errors -join " "
    throw "Could not find a supported Python >=3.11,<3.14 for local audio evidence. $details"
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

function Assert-PathInsideRepo {
    param([string]$RepoRoot, [string]$Path, [string]$Label)

    $repoFullPath = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $targetFullPath = [System.IO.Path]::GetFullPath($Path)
    if ($targetFullPath.Equals($repoFullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must not be the repository root."
    }
    if (
        -not $targetFullPath.StartsWith($repoFullPath + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase) -and
        -not $targetFullPath.StartsWith($repoFullPath + [System.IO.Path]::AltDirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "$Label must stay inside the repository. Got: $targetFullPath"
    }
}

function Assert-RecreateVenvTarget {
    param([string]$VenvPath)

    if (-not (Test-Path -LiteralPath $VenvPath)) {
        return
    }

    $marker = Join-Path $VenvPath "pyvenv.cfg"
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        throw "Refusing to recreate '$VenvPath' because it does not look like a Python virtualenv with pyvenv.cfg. Delete it manually if this path is intentional."
    }
}

function Resolve-VenvPython {
    param([string]$VenvPath)

    $windowsPython = Join-Path $VenvPath "Scripts\python.exe"
    if (Test-Path -LiteralPath $windowsPython -PathType Leaf) {
        return (Resolve-Path -LiteralPath $windowsPython).Path
    }

    $posixPython = Join-Path $VenvPath "bin/python"
    if (Test-Path -LiteralPath $posixPython -PathType Leaf) {
        return (Resolve-Path -LiteralPath $posixPython).Path
    }

    throw "Audio local venv Python was not found under $VenvPath."
}

function Get-RequiredPackages {
    param([string]$ActionName)

    $packages = New-Object System.Collections.Generic.List[string]
    $packages.Add("numpy")

    $soundDeviceActions = @(
        "capture",
        "collect-headphone-evidence",
        "list-devices",
        "play-manual",
        "preflight",
        "probe-route",
        "sweep-routes"
    )
    if ($soundDeviceActions -contains $ActionName) {
        $packages.Add("sounddevice")
    }

    return $packages.ToArray()
}

function Get-ForwardArguments {
    param([string[]]$Arguments)

    return @($Arguments | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

$repoRoot = Resolve-RepoRoot
$venvPath = if ([string]::IsNullOrWhiteSpace($Venv)) {
    Join-Path $repoRoot ".venv-audio-local"
} elseif ([System.IO.Path]::IsPathRooted($Venv)) {
    [System.IO.Path]::GetFullPath($Venv)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Venv))
}
Assert-PathInsideRepo -RepoRoot $repoRoot -Path $venvPath -Label "Audio local venv"

$pythonPath = Resolve-SupportedPython -RequestedPython $Python -RepoRoot $repoRoot

if ($RecreateVenv -and (Test-Path -LiteralPath $venvPath)) {
    Assert-RecreateVenvTarget -VenvPath $venvPath
    Remove-Item -LiteralPath $venvPath -Recurse -Force
}

if (-not (Test-Path -LiteralPath $venvPath)) {
    Invoke-CheckedCommand `
        -Label "create audio local virtualenv" `
        -FilePath $pythonPath `
        -Arguments @("-m", "venv", $venvPath) `
        -WorkingDirectory $repoRoot
}

$audioPython = Resolve-VenvPython -VenvPath $venvPath
Assert-SupportedPython -FilePath $audioPython -Label "Audio local Python"

if (-not $SkipDependencyInstall) {
    Invoke-CheckedCommand `
        -Label "upgrade audio local pip" `
        -FilePath $audioPython `
        -Arguments @("-m", "pip", "install", "--upgrade", "pip") `
        -WorkingDirectory $repoRoot

    $packages = Get-RequiredPackages -ActionName $Action
    Invoke-CheckedCommand `
        -Label "install audio local dependencies" `
        -FilePath $audioPython `
        -Arguments (@("-m", "pip", "install") + $packages) `
        -WorkingDirectory $repoRoot
}

$scriptPath = Join-Path $repoRoot "scripts\run_headphone_isolation_check.py"
$forwardArgs = Get-ForwardArguments -Arguments $CommandArgs
Invoke-CheckedCommand `
    -Label "headphone isolation $Action" `
    -FilePath $audioPython `
    -Arguments (@($scriptPath, $Action) + $forwardArgs) `
    -WorkingDirectory $repoRoot
