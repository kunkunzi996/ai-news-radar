[CmdletBinding()]
param(
    [string]$RadarRoot = "",
    [string]$DbPath = "E:\AI-news-reader\we-mp-rss-sidecar\data\db.db",
    [string]$CollectStatusFile = "E:\AI-news-reader\wechat-collect-status.json",
    [string]$SecretFile = "",
    [string]$StateFile = "E:\AI-news-reader\wechat-watchdog-state.json",
    [string]$RunStatusFile = "E:\AI-news-reader\wechat-watchdog-run-status.json",
    [string]$LogFile = "E:\AI-news-reader\wechat-watchdog.log",
    [double]$StaleHours = 14,
    [string]$PythonExe = "",
    [string]$ProbeFixtureFile = "",
    [string]$PushSinkFile = ""
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

if (-not $RadarRoot) { $RadarRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }
if (-not $SecretFile) { $SecretFile = Join-Path $RadarRoot "local-secrets\meow-push.json" }
if (-not $PythonExe) { $PythonExe = Join-Path $RadarRoot ".venv\Scripts\python.exe" }

$script:RunId = [guid]::NewGuid().ToString("N")
$script:StartedAt = (Get-Date).ToUniversalTime().ToString("o")
$script:WatchdogMutex = $null
$script:MutexAcquired = $false
$script:RunStatus = [ordered]@{
    schema_version = 1
    state = "running"
    stage = "starting"
    exit_code = $null
    message_code = "starting"
    started_at = $script:StartedAt
    finished_at = $null
}

function Get-NowIso {
    return (Get-Date).ToUniversalTime().ToString("o")
}

function Write-SafeLog([string]$Event, [string]$Detail = "") {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Event
    if ($Detail) { $line = "$line $Detail" }
    [Console]::Out.WriteLine($line)
    if (-not $LogFile) { return }
    try {
        $directory = Split-Path -Parent $LogFile
        if ($directory -and -not (Test-Path -LiteralPath $directory)) {
            [IO.Directory]::CreateDirectory($directory) | Out-Null
        }
        $encoding = New-Object Text.UTF8Encoding($false)
        [IO.File]::AppendAllText($LogFile, $line + [Environment]::NewLine, $encoding)
    } catch {
        # 日志写失败不能覆盖原始业务结果，也不能记录原始异常。
    }
}

function Write-AtomicJson([string]$Path, [object]$Value) {
    if (-not $Path) { return }
    $directory = Split-Path -Parent $Path
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
        [IO.Directory]::CreateDirectory($directory) | Out-Null
    }
    $temp = "$Path.$($script:RunId).tmp"
    $json = $Value | ConvertTo-Json -Depth 12
    $encoding = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($temp, $json + [Environment]::NewLine, $encoding)
    if (Test-Path -LiteralPath $Path) {
        $backup = "$Path.$($script:RunId).backup"
        try {
            [IO.File]::Replace($temp, $Path, $backup)
        } finally {
            if (Test-Path -LiteralPath $backup) {
                [IO.File]::Delete($backup)
            }
        }
    } else {
        [IO.File]::Move($temp, $Path)
    }
}

function Write-RunStatus {
    Write-AtomicJson $RunStatusFile $script:RunStatus
}

function Complete-Run([string]$State, [string]$Stage, [string]$MessageCode, [int]$ExitCode) {
    $script:RunStatus.state = $State
    $script:RunStatus.stage = $Stage
    $script:RunStatus.exit_code = $ExitCode
    $script:RunStatus.message_code = $MessageCode
    $script:RunStatus.finished_at = Get-NowIso
    Write-RunStatus
}

function Release-WatchdogMutex {
    if ($script:WatchdogMutex) {
        if ($script:MutexAcquired) {
            try { $script:WatchdogMutex.ReleaseMutex() } catch {}
        }
        $script:WatchdogMutex.Dispose()
        $script:WatchdogMutex = $null
        $script:MutexAcquired = $false
    }
}

function Get-PropertyValue([object]$Object, [string]$Name, [object]$Default = $null) {
    if ($null -ne $Object -and $null -ne $Object.PSObject.Properties[$Name]) {
        return $Object.$Name
    }
    return $Default
}

function Test-SafeCode([object]$Value) {
    return ([string]$Value) -match "^[a-z0-9_]{1,64}$"
}

function Get-SafeText([object]$Value, [int]$MaxLength) {
    $text = ([string]$Value) -replace "[\r\n\t]", " "
    $text = $text.Trim()
    if ($text.Length -gt $MaxLength) { $text = $text.Substring(0, $MaxLength) }
    return $text
}

function New-DefaultIncidentState {
    return [ordered]@{
        schema_version = 1
        status = "ok"
        primary_reason = "ok"
        latest_reason = "ok"
        incident_started_at = $null
        alert_sent_at = $null
        recovery_pending = $false
        updated_at = Get-NowIso
    }
}

function Read-IncidentState {
    if (-not (Test-Path -LiteralPath $StateFile)) {
        return @{ Ok = $true; Exists = $false; Value = (New-DefaultIncidentState) }
    }
    try {
        $value = Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
        $status = [string](Get-PropertyValue $value "status" "")
        $primaryReason = [string](Get-PropertyValue $value "primary_reason" "")
        $latestReason = [string](Get-PropertyValue $value "latest_reason" "")
        if (($status -notin @("ok", "alerting")) -or -not (Test-SafeCode $primaryReason) -or -not (Test-SafeCode $latestReason)) {
            return @{ Ok = $false; Code = "incident_state_invalid" }
        }
        return @{
            Ok = $true
            Exists = $true
            Value = [ordered]@{
                schema_version = 1
                status = $status
                primary_reason = $primaryReason
                latest_reason = $latestReason
                incident_started_at = Get-PropertyValue $value "incident_started_at" $null
                alert_sent_at = Get-PropertyValue $value "alert_sent_at" $null
                recovery_pending = [bool](Get-PropertyValue $value "recovery_pending" $false)
                updated_at = Get-PropertyValue $value "updated_at" $null
            }
        }
    } catch {
        return @{ Ok = $false; Code = "incident_state_unreadable" }
    }
}

function Read-MeowConfig {
    if (-not (Test-Path -LiteralPath $SecretFile)) {
        return @{ Ok = $false; Code = "secret_missing" }
    }
    try {
        $config = Get-Content -LiteralPath $SecretFile -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
        $nickname = ([string](Get-PropertyValue $config "nickname" "")).Trim()
        if (-not $nickname) { return @{ Ok = $false; Code = "secret_nickname_empty" } }
        if ($nickname.Contains("/")) { return @{ Ok = $false; Code = "secret_nickname_invalid" } }
        return @{ Ok = $true; Config = $config; Nickname = $nickname }
    } catch {
        return @{ Ok = $false; Code = "secret_invalid" }
    }
}

function New-WatchdogFailedVerdict {
    return [pscustomobject]@{
        schema_version = 1
        decision = "alert"
        reason = "watchdog_failed"
        title = "微信健康看门狗异常"
        message = "微信健康检查脚本未能正常运行，请检查本机运行状态。"
    }
}

function ConvertTo-ValidVerdict([object]$Candidate) {
    if ($null -eq $Candidate) { return $null }
    $decision = [string](Get-PropertyValue $Candidate "decision" "")
    $reason = [string](Get-PropertyValue $Candidate "reason" "")
    $title = Get-SafeText (Get-PropertyValue $Candidate "title" "") 100
    $message = Get-SafeText (Get-PropertyValue $Candidate "message" "") 600
    if (($decision -notin @("healthy", "alert", "defer")) -or -not (Test-SafeCode $reason) -or -not $title -or -not $message) {
        return $null
    }
    return [pscustomobject]@{
        schema_version = 1
        decision = $decision
        reason = $reason
        title = $title
        message = $message
    }
}

function Read-ProbeVerdict {
    try {
        if ($ProbeFixtureFile) {
            $raw = Get-Content -LiteralPath $ProbeFixtureFile -Raw -Encoding UTF8
        } else {
            $probeScript = Join-Path $PSScriptRoot "wechat_health_probe.py"
            if (-not (Test-Path -LiteralPath $PythonExe)) {
                return @{ Ok = $false; Code = "python_missing" }
            }
            if (-not (Test-Path -LiteralPath $probeScript)) {
                return @{ Ok = $false; Code = "probe_missing" }
            }

            # A hidden scheduled task has no console pipe. Capture Python output explicitly
            # so its JSON verdict remains available in both interactive and task contexts.
            $staleHoursText = $StaleHours.ToString([Globalization.CultureInfo]::InvariantCulture)
            $startInfo = New-Object System.Diagnostics.ProcessStartInfo
            $startInfo.FileName = $PythonExe
            $startInfo.Arguments = ('"{0}" "--db-path" "{1}" "--status-path" "{2}" "--stale-hours" "{3}"' -f $probeScript, $DbPath, $CollectStatusFile, $staleHoursText)
            $startInfo.WorkingDirectory = $RadarRoot
            $startInfo.UseShellExecute = $false
            $startInfo.CreateNoWindow = $true
            $startInfo.RedirectStandardOutput = $true
            $startInfo.StandardOutputEncoding = [Text.Encoding]::UTF8

            $process = New-Object System.Diagnostics.Process
            $process.StartInfo = $startInfo
            if (-not $process.Start()) {
                return @{ Ok = $false; Code = "probe_process_failed" }
            }
            try {
                $raw = $process.StandardOutput.ReadToEnd()
                $process.WaitForExit()
                $processExitCode = $process.ExitCode
            } finally {
                $process.Dispose()
            }
            if ($processExitCode -ne 0) {
                return @{ Ok = $false; Code = "probe_process_failed" }
            }
        }
        $verdict = ConvertTo-ValidVerdict ($raw | ConvertFrom-Json -ErrorAction Stop)
        if ($null -eq $verdict) {
            return @{ Ok = $false; Code = "probe_output_invalid" }
        }
        return @{ Ok = $true; Verdict = $verdict }
    } catch {
        return @{ Ok = $false; Code = "probe_output_invalid" }
    }
}

function Add-PushSinkEvent([string]$Kind, [pscustomobject]$Verdict, [int]$ResponseStatus) {
    $directory = Split-Path -Parent $PushSinkFile
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
        [IO.Directory]::CreateDirectory($directory) | Out-Null
    }
    $event = [ordered]@{
        kind = $Kind
        reason = $Verdict.reason
        title = $Verdict.title
        message = $Verdict.message
        response_status = $ResponseStatus
    }
    $encoding = New-Object Text.UTF8Encoding($false)
    [IO.File]::AppendAllText($PushSinkFile, ($event | ConvertTo-Json -Compress) + [Environment]::NewLine, $encoding)
}

function Send-Meow([object]$Config, [string]$Nickname, [string]$Kind, [pscustomobject]$Verdict) {
    if ($PushSinkFile) {
        $configuredStatus = Get-PropertyValue $Config "test_response_status" 200
        try { $responseStatus = [int]$configuredStatus } catch { $responseStatus = 0 }
        Add-PushSinkEvent $Kind $Verdict $responseStatus
        if ($responseStatus -eq 200) { return @{ Ok = $true; Code = "sent" } }
        return @{ Ok = $false; Code = "api_status_invalid" }
    }

    try {
        $uri = "https://api.chuckfang.com/{0}" -f [uri]::EscapeDataString($Nickname)
        $body = @{ title = $Verdict.title; msg = $Verdict.message } | ConvertTo-Json -Depth 4
        $bytes = [Text.Encoding]::UTF8.GetBytes($body)
        $response = Invoke-RestMethod -Uri $uri -Method Post -Body $bytes -ContentType "application/json; charset=utf-8" -TimeoutSec 15
        if ($response -is [string]) {
            $response = $response | ConvertFrom-Json -ErrorAction Stop
        }
        $status = Get-PropertyValue $response "status" $null
        if ([string]$status -ne "200") {
            return @{ Ok = $false; Code = "api_status_invalid" }
        }
        return @{ Ok = $true; Code = "sent" }
    } catch {
        return @{ Ok = $false; Code = "push_transport_failed" }
    }
}

function New-RunResult([string]$State, [string]$Stage, [string]$MessageCode, [int]$ExitCode) {
    return @{
        State = $State
        Stage = $Stage
        MessageCode = $MessageCode
        ExitCode = $ExitCode
    }
}

function Invoke-Watchdog {
    $configRead = Read-MeowConfig
    if (-not $configRead.Ok) {
        Write-SafeLog "config_failed" $configRead.Code
        return New-RunResult "failed" "config" $configRead.Code 3
    }

    $probeRead = Read-ProbeVerdict
    $probeFailed = -not $probeRead.Ok
    if ($probeFailed) {
        Write-SafeLog "probe_failed" $probeRead.Code
        $verdict = New-WatchdogFailedVerdict
    } else {
        $verdict = $probeRead.Verdict
    }

    $incidentRead = Read-IncidentState
    if (-not $incidentRead.Ok) {
        Write-SafeLog "incident_state_failed" $incidentRead.Code
        $probeFailed = $true
        $verdict = New-WatchdogFailedVerdict
        $incident = New-DefaultIncidentState
    } else {
        $incident = $incidentRead.Value
    }

    if ($verdict.decision -eq "defer") {
        Write-SafeLog "deferred" $verdict.reason
        return New-RunResult "deferred" "probe" $verdict.reason 0
    }

    if ($verdict.decision -eq "alert") {
        if ($incident.status -eq "alerting") {
            $incident.latest_reason = $verdict.reason
            $incident.recovery_pending = $false
            $incident.updated_at = Get-NowIso
            Write-AtomicJson $StateFile $incident
            Write-SafeLog "alert_suppressed" $verdict.reason
            if ($probeFailed) {
                return New-RunResult "failed" "probe" "watchdog_failed" 4
            }
            return New-RunResult "succeeded" "alerting" "alert_suppressed" 0
        }

        $push = Send-Meow $configRead.Config $configRead.Nickname "alert" $verdict
        if (-not $push.Ok) {
            Write-SafeLog "alert_push_failed" $push.Code
            return New-RunResult "failed" "push" $push.Code 5
        }
        $nowIso = Get-NowIso
        $incident = [ordered]@{
            schema_version = 1
            status = "alerting"
            primary_reason = $verdict.reason
            latest_reason = $verdict.reason
            incident_started_at = $nowIso
            alert_sent_at = $nowIso
            recovery_pending = $false
            updated_at = $nowIso
        }
        Write-AtomicJson $StateFile $incident
        Write-SafeLog "alert_sent" $verdict.reason
        if ($probeFailed) {
            return New-RunResult "failed" "probe" "watchdog_failed" 4
        }
        return New-RunResult "succeeded" "alerting" "alert_sent" 0
    }

    if ($incident.status -eq "alerting") {
        $recovery = [pscustomobject]@{
            schema_version = 1
            decision = "healthy"
            reason = "ok"
            title = "微信采集已恢复"
            message = "微信采集已恢复正常。"
        }
        $push = Send-Meow $configRead.Config $configRead.Nickname "recovery" $recovery
        if (-not $push.Ok) {
            $incident.latest_reason = "ok"
            $incident.recovery_pending = $true
            $incident.updated_at = Get-NowIso
            Write-AtomicJson $StateFile $incident
            Write-SafeLog "recovery_push_failed" $push.Code
            return New-RunResult "failed" "recovery" $push.Code 5
        }
        $incident = New-DefaultIncidentState
        Write-AtomicJson $StateFile $incident
        Write-SafeLog "recovery_sent"
        return New-RunResult "succeeded" "recovery" "recovery_sent" 0
    }

    $incident = New-DefaultIncidentState
    Write-AtomicJson $StateFile $incident
    Write-SafeLog "healthy"
    return New-RunResult "succeeded" "healthy" "healthy" 0
}

$script:WatchdogMutex = New-Object Threading.Mutex($false, "Local\AI-News-Radar-WeChat-HealthWatchdog")
try {
    $script:MutexAcquired = $script:WatchdogMutex.WaitOne(0)
} catch [Threading.AbandonedMutexException] {
    $script:MutexAcquired = $true
}
if (-not $script:MutexAcquired) {
    [Console]::Out.WriteLine("busy: WeChat health watchdog is already running")
    $script:WatchdogMutex.Dispose()
    exit 0
}

$exitCode = 1
try {
    Write-RunStatus
    $result = Invoke-Watchdog
    Complete-Run $result.State $result.Stage $result.MessageCode $result.ExitCode
    $exitCode = $result.ExitCode
} catch {
    try {
        Complete-Run "failed" "watchdog" "watchdog_failed" 1
    } catch {}
    Write-SafeLog "watchdog_failed"
    $exitCode = 1
} finally {
    Release-WatchdogMutex
}
exit $exitCode
