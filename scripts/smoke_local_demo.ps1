param(
    [string]$GatewayHost = $(if ($env:GATEWAY_HOST) { $env:GATEWAY_HOST } else { "127.0.0.1" }),
    [int]$GatewayPort = $(if ($env:GATEWAY_PORT) { [int]$env:GATEWAY_PORT } else { 8000 }),
    [string]$GatewayPython = $(if ($env:GATEWAY_PYTHON) { $env:GATEWAY_PYTHON } else { "" }),
    [int]$RequestTimeoutSeconds = $(if ($env:REQUEST_TIMEOUT_SECONDS) { [int]$env:REQUEST_TIMEOUT_SECONDS } else { 3 }),
    [int]$StartTimeoutSeconds = $(if ($env:SMOKE_START_TIMEOUT_SECONDS) { [int]$env:SMOKE_START_TIMEOUT_SECONDS } else { 20 })
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

function Resolve-GatewayPython {
    param([string]$RepoRoot, [string]$Candidate)

    if (-not [string]::IsNullOrWhiteSpace($Candidate)) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
        $command = Get-Command $Candidate -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
        throw "Gateway Python was not found at '$Candidate'."
    }

    $windowsVenv = Join-Path $RepoRoot "services\gateway\.venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $windowsVenv -PathType Leaf) {
        return (Resolve-Path -LiteralPath $windowsVenv).Path
    }

    $posixVenv = Join-Path $RepoRoot "services/gateway/.venv/bin/python"
    if (Test-Path -LiteralPath $posixVenv -PathType Leaf) {
        return (Resolve-Path -LiteralPath $posixVenv).Path
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }

    throw "Unable to find a gateway Python interpreter. Create services/gateway/.venv or pass -GatewayPython."
}

function Require {
    param([bool]$Condition, [string]$Message)

    if (-not $Condition) {
        throw $Message
    }
}

function Get-Json {
    param([string]$Url, [int]$TimeoutSeconds)

    $response = Invoke-WebRequest -Uri $Url -Headers @{ Accept = "application/json" } -TimeoutSec $TimeoutSeconds
    Require ($response.StatusCode -eq 200) "Expected 200 for $Url, got $($response.StatusCode)."
    return [pscustomobject]@{
        body = $response.Content
        data = ($response.Content | ConvertFrom-Json -NoEnumerate)
        document = [System.Text.Json.JsonDocument]::Parse($response.Content)
    }
}

function Require-ObjectPropertyNames {
    param(
        [System.Text.Json.JsonElement]$Element,
        [string[]]$ExpectedNames,
        [string]$Message
    )

    Require ($Element.ValueKind -eq [System.Text.Json.JsonValueKind]::Object) $Message
    $actualNames = @($Element.EnumerateObject() | ForEach-Object { $_.Name })
    Require ($actualNames.Count -eq $ExpectedNames.Count) $Message
    foreach ($name in $ExpectedNames) {
        Require ($actualNames -contains $name) $Message
    }
}

function Require-JsonArrayProperty {
    param(
        [System.Text.Json.JsonElement]$Element,
        [string]$PropertyName,
        [bool]$RequireNonEmpty,
        [string]$Message
    )

    [System.Text.Json.JsonElement]$property = [System.Text.Json.JsonElement]::new()
    Require ($Element.TryGetProperty($PropertyName, [ref]$property)) $Message
    Require ($property.ValueKind -eq [System.Text.Json.JsonValueKind]::Array) $Message
    if ($RequireNonEmpty) {
        Require ($property.GetArrayLength() -gt 0) $Message
    }
}

function Require-ExactHealthPayload {
    param([pscustomobject]$Payload)

    Require-ObjectPropertyNames -Element $Payload.document.RootElement -ExpectedNames @("status") -Message "Unexpected /health payload."
    Require ($Payload.data.status -eq "ok") "Unexpected /health payload."
}

function Test-GatewayHealth {
    param([string]$BaseUrl, [int]$TimeoutSeconds)

    try {
        $health = Get-Json -Url "$BaseUrl/health" -TimeoutSeconds $TimeoutSeconds
        Require-ExactHealthPayload -Payload $health
        return $true
    } catch {
        return $false
    }
}

function Parse-SseEvents {
    param([string]$Payload)

    $events = @()
    $normalized = $Payload -replace "`r`n", "`n"
    foreach ($block in ($normalized -split "`n`n")) {
        $lines = @($block -split "`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if ($lines.Count -eq 0) {
            continue
        }
        if (@($lines | Where-Object { -not $_.StartsWith(":") }).Count -eq 0) {
            continue
        }

        $eventName = $null
        $dataLines = New-Object System.Collections.Generic.List[string]
        foreach ($line in $lines) {
            if ($line.StartsWith("event: ")) {
                $eventName = $line.Substring("event: ".Length)
            } elseif ($line.StartsWith("data: ")) {
                $dataLines.Add($line.Substring("data: ".Length))
            }
        }

        Require ($null -ne $eventName) "SSE payload missing event name: $Payload"
        Require ($dataLines.Count -gt 0) "SSE payload missing data lines: $Payload"
        $dataJson = $dataLines -join "`n"
        $events += [pscustomobject]@{
            event = $eventName
            data_json = $dataJson
            data = ($dataJson | ConvertFrom-Json -NoEnumerate)
            data_document = [System.Text.Json.JsonDocument]::Parse($dataJson)
        }
    }

    return @($events)
}

$repoRoot = Resolve-RepoRoot
$gatewayDir = Join-Path $repoRoot "services\gateway"
$gatewayPythonPath = Resolve-GatewayPython -RepoRoot $repoRoot -Candidate $GatewayPython
$baseUrl = "http://${GatewayHost}:${GatewayPort}"
$startedGateway = $false
$gatewayProcess = $null
$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("language-smoke-" + [guid]::NewGuid().ToString())
$stdoutLog = Join-Path $tmpDir "gateway.stdout.log"
$stderrLog = Join-Path $tmpDir "gateway.stderr.log"

New-Item -ItemType Directory -Path $tmpDir | Out-Null

try {
    if (Test-GatewayHealth -BaseUrl $baseUrl -TimeoutSeconds $RequestTimeoutSeconds) {
        Write-Host "Reusing existing gateway at $baseUrl"
    } else {
        Write-Host "Starting a temporary gateway at $baseUrl"
        $gatewayProcess = Start-Process `
            -FilePath $gatewayPythonPath `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", $GatewayHost, "--port", "$GatewayPort", "--log-level", "warning") `
            -WorkingDirectory $gatewayDir `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog `
            -WindowStyle Hidden `
            -PassThru
        $startedGateway = $true

        $deadline = (Get-Date).AddSeconds($StartTimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            if ($gatewayProcess.HasExited) {
                throw "Temporary gateway exited before becoming healthy with code $($gatewayProcess.ExitCode)."
            }
            if (Test-GatewayHealth -BaseUrl $baseUrl -TimeoutSeconds $RequestTimeoutSeconds) {
                break
            }
            Start-Sleep -Milliseconds 500
        }
        Require (Test-GatewayHealth -BaseUrl $baseUrl -TimeoutSeconds $RequestTimeoutSeconds) "Gateway did not become healthy within ${StartTimeoutSeconds}s."
    }

    Write-Host "Validating local demo gateway endpoints"
    $health = Get-Json -Url "$baseUrl/health" -TimeoutSeconds $RequestTimeoutSeconds
    Require-ExactHealthPayload -Payload $health

    $session = Get-Json -Url "$baseUrl/v1/session" -TimeoutSeconds $RequestTimeoutSeconds
    Require (-not [string]::IsNullOrWhiteSpace($session.data.session_id)) "/v1/session missing session_id."
    Require (-not [string]::IsNullOrWhiteSpace($session.data.mode)) "/v1/session missing mode."
    Require-JsonArrayProperty -Element $session.document.RootElement -PropertyName "speakers" -RequireNonEmpty $false -Message "/v1/session missing speakers list."
    Require ($session.data.PSObject.Properties.Name -contains "top_speaker_id") "/v1/session missing top_speaker_id."

    $preview = Get-Json -Url "$baseUrl/v1/session?mode=FOCUS" -TimeoutSeconds $RequestTimeoutSeconds
    Require ($preview.data.mode -eq "FOCUS") "Expected FOCUS preview, got '$($preview.data.mode)'."
    Require-JsonArrayProperty -Element $preview.document.RootElement -PropertyName "speakers" -RequireNonEmpty $true -Message "FOCUS preview returned no speakers list."
    Require (-not [string]::IsNullOrWhiteSpace($preview.data.top_speaker_id)) "FOCUS preview missing top_speaker_id."

    $firstSpeaker = @($preview.data.speakers)[0]
    Require (-not [string]::IsNullOrWhiteSpace($firstSpeaker.speaker_id)) "Preview speaker missing speaker_id."
    Require (-not [string]::IsNullOrWhiteSpace($firstSpeaker.display_name)) "Preview speaker missing display_name."

    $stream = Invoke-WebRequest `
        -Uri "$baseUrl/v1/events/stream?mode=FOCUS&max_events=1" `
        -Headers @{ Accept = "text/event-stream" } `
        -TimeoutSec $RequestTimeoutSeconds
    Require ($stream.StatusCode -eq 200) "Expected 200 for /v1/events/stream, got $($stream.StatusCode)."
    $contentType = [string]$stream.Headers["Content-Type"]
    Require ($contentType.StartsWith("text/event-stream")) "Unexpected SSE content type: '$contentType'."

    $events = Parse-SseEvents -Payload $stream.Content
    Require ($events.Count -eq 1) "Expected exactly one SSE event, got $($events.Count)."
    $event = $events[0]
    Require ($event.event -eq "session.snapshot") "Expected session.snapshot SSE event, got '$($event.event)'."
    Require ($null -ne $event.data.session) "SSE event missing session payload."
    Require ($event.data.session.session_id -eq $preview.data.session_id) "SSE session_id did not match FOCUS preview."
    Require ($event.data.session.mode -eq "FOCUS") "Expected FOCUS SSE snapshot, got '$($event.data.session.mode)'."
    Require ($event.data.session.top_speaker_id -eq $preview.data.top_speaker_id) "SSE top_speaker_id did not match FOCUS preview."
    $eventSessionElement = $event.data_document.RootElement.GetProperty("session")
    Require-JsonArrayProperty -Element $eventSessionElement -PropertyName "speakers" -RequireNonEmpty $true -Message "SSE snapshot returned no speakers list."

    Write-Host "Verified /health, /v1/session, and /v1/events/stream against the local demo baseline."
    Write-Host "Local demo smoke check passed"
} catch {
    if (Test-Path -LiteralPath $stderrLog -PathType Leaf) {
        $stderr = Get-Content -LiteralPath $stderrLog -Raw
        if (-not [string]::IsNullOrWhiteSpace($stderr)) {
            Write-Error "Gateway stderr log:`n$stderr" -ErrorAction Continue
        }
    }
    if (Test-Path -LiteralPath $stdoutLog -PathType Leaf) {
        $stdout = Get-Content -LiteralPath $stdoutLog -Raw
        if (-not [string]::IsNullOrWhiteSpace($stdout)) {
            Write-Error "Gateway stdout log:`n$stdout" -ErrorAction Continue
        }
    }
    throw
} finally {
    if ($startedGateway -and $gatewayProcess -and -not $gatewayProcess.HasExited) {
        Stop-Process -Id $gatewayProcess.Id -Force
        Wait-Process -Id $gatewayProcess.Id -Timeout 5 -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
}
