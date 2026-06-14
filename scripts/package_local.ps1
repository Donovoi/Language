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

function Invoke-GitCapture {
    param(
        [string]$RepoRoot,
        [string[]]$Arguments
    )

    $output = & git -c "safe.directory=$RepoRoot" -C $RepoRoot @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
    return (($output | Out-String).Trim())
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
    param(
        [string]$RepoRoot,
        [string]$ReleaseVersion,
        [System.Collections.Generic.List[string]]$ArtifactPaths
    )

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
    $ArtifactPaths.Add($tarPath)
    $ArtifactPaths.Add($zipPath)
}

function Build-GatewayPackage {
    param(
        [string]$RepoRoot,
        [string]$PythonPath,
        [System.Collections.Generic.List[string]]$ArtifactPaths
    )

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
    $ArtifactPaths.Add($sdists[0].FullName)
    $ArtifactPaths.Add($wheels[0].FullName)
}

function Write-LocalArtifactManifest {
    param(
        [string]$RepoRoot,
        [string]$ReleaseVersion,
        [string]$ActionName,
        [string[]]$ArtifactPaths,
        [bool]$AllowDirtyTree
    )

    if ($ArtifactPaths.Count -eq 0) {
        throw "No local artifacts were built."
    }

    $artifactRoot = Join-Path $RepoRoot "dist\local-release-artifacts"
    if (Test-Path -LiteralPath $artifactRoot) {
        Remove-Item -LiteralPath $artifactRoot -Recurse -Force -ErrorAction Stop
    }
    if (Test-Path -LiteralPath $artifactRoot) {
        throw "Could not clear previous local artifact handoff directory: $artifactRoot"
    }
    New-Item -ItemType Directory -Path $artifactRoot -Force -ErrorAction Stop | Out-Null

    $copiedFiles = New-Object System.Collections.Generic.List[System.IO.FileInfo]
    foreach ($artifactPath in $ArtifactPaths) {
        if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
            throw "Built artifact was not found: $artifactPath"
        }
        $sourceFile = Get-Item -LiteralPath $artifactPath -ErrorAction Stop
        $destinationName = $sourceFile.Name
        if ($destinationName -eq "language_gateway-$ReleaseVersion.tar.gz") {
            $destinationName = "language-gateway-$ReleaseVersion.tar.gz"
        }
        $destinationPath = Join-Path $artifactRoot $destinationName
        Copy-Item -LiteralPath $sourceFile.FullName -Destination $destinationPath -Force -ErrorAction Stop
        $copiedFiles.Add((Get-Item -LiteralPath $destinationPath -ErrorAction Stop))
    }

    $files = @($copiedFiles | Sort-Object Name)
    if ($files.Count -eq 0) {
        throw "No files were copied into $artifactRoot."
    }

    $checksumLines = New-Object System.Collections.Generic.List[string]
    $artifactLines = New-Object System.Collections.Generic.List[string]
    foreach ($file in $files) {
        $digest = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $checksumLines.Add("$digest  $($file.Name)")
        $artifactLines.Add("- ``$($file.Name)``")
    }

    $checksumPath = Join-Path $artifactRoot "SHA256SUMS.txt"
    Set-Content -LiteralPath $checksumPath -Value ($checksumLines -join "`n") -Encoding UTF8
    Add-Content -LiteralPath $checksumPath -Value "" -Encoding UTF8

    $commit = Invoke-GitCapture -RepoRoot $RepoRoot -Arguments @("rev-parse", "HEAD")
    $ref = Invoke-GitCapture -RepoRoot $RepoRoot -Arguments @("rev-parse", "--abbrev-ref", "HEAD")
    $dirtyStatus = & git -c "safe.directory=$RepoRoot" -C $RepoRoot status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw "git status --porcelain failed with exit code $LASTEXITCODE."
    }
    $dirtyTree = [bool]$dirtyStatus
    $generatedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $scope = switch ($ActionName) {
        "source-bundle" { "local source bundle artifacts only" }
        "gateway-package" { "local gateway package artifacts only" }
        default { "local source bundle and gateway package artifacts only" }
    }
    $manifestLines = @(
        "# local artifact manifest",
        "",
        "- version: ``$ReleaseVersion``",
        "- channel: ``local``",
        "- scope: ``$scope``",
        "- commit: ``$commit``",
        "- ref: ``$ref``",
        "- dirty_tree: ``$($dirtyTree.ToString().ToLowerInvariant())``",
        "- allow_dirty: ``$($AllowDirtyTree.ToString().ToLowerInvariant())``",
        "- generated_at_utc: ``$generatedAt``",
        "- smoke runbook: ``docs/development/internal-beta-smoke-runbook.md``"
    )
    if ($ActionName -eq "all" -or $ActionName -eq "gateway-package") {
        $manifestLines += "- gateway command: install the gateway wheel or sdist in a virtualenv, then run ``language-gateway --host 127.0.0.1 --port 8000``"
    }
    $manifestLines += @(
        "- auth note: app artifacts can use ``FIELD_APP_AUTH_TOKEN`` for controlled internal smoke only; rotate the matching gateway token after use",
        "- limitation: this is not the full GitHub Actions release manifest; Flutter artifacts, workflow run metadata, and publish-release assets are not included",
        "",
        "## Files"
    ) + $artifactLines

    $manifestPath = Join-Path $artifactRoot "manifest.md"
    Set-Content -LiteralPath $manifestPath -Value ($manifestLines -join "`n") -Encoding UTF8
    Add-Content -LiteralPath $manifestPath -Value "" -Encoding UTF8

    Write-Host "Wrote $manifestPath"
    Write-Host "Wrote $checksumPath"
}

$repoRoot = Resolve-RepoRoot
$pythonPath = $null
if ($Action -eq "all" -or $Action -eq "gateway-package") {
    $pythonPath = Resolve-Executable -Candidate $Python -Label "Python"
    Assert-SupportedPython -FilePath $pythonPath -Label "Python"
}
$releaseVersion = Get-ReleaseVersion -RepoRoot $repoRoot -OverrideVersion $Version
Assert-CleanGitTree -RepoRoot $repoRoot -AllowDirtyTree $AllowDirty.IsPresent
$builtArtifacts = New-Object System.Collections.Generic.List[string]

if ($Action -eq "all" -or $Action -eq "source-bundle") {
    Build-SourceBundle -RepoRoot $repoRoot -ReleaseVersion $releaseVersion -ArtifactPaths $builtArtifacts
}

if ($Action -eq "all" -or $Action -eq "gateway-package") {
    Build-GatewayPackage -RepoRoot $repoRoot -PythonPath $pythonPath -ArtifactPaths $builtArtifacts
}

Write-LocalArtifactManifest `
    -RepoRoot $repoRoot `
    -ReleaseVersion $releaseVersion `
    -ActionName $Action `
    -ArtifactPaths $builtArtifacts.ToArray() `
    -AllowDirtyTree $AllowDirty.IsPresent

Write-Host ""
Write-Host "Local package build passed."
