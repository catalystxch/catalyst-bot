param(
    [string]$TracePath = 'E:\catalyst-stability-monitor-0d1096e-clean\trace-60s-clean.jsonl',
    [int]$ExpectedPid = 118100,
    [string]$ExpectedExe = 'E:\catalyst-heartbeat-0d1096e-build\dist\Catalyst\Catalyst.exe',
    [string]$ExpectedHash = 'F68A0A8678FBACABA2CECCA66B0ECA8433837C4509175407B6A02B042EFF1023',
    [int]$RequiredHours = 24,
    [int]$MaximumGapSeconds = 120
)

$ErrorActionPreference = 'Stop'
function Parse-Utc([string]$Value) {
    return [datetimeoffset]::Parse(
        $Value,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AssumeUniversal
    )
}
$rows = @(Get-Content -LiteralPath $TracePath | ForEach-Object { $_ | ConvertFrom-Json -DateKind String })
$starts = @($rows | Where-Object { $_.kind -eq 'start' })
$samples = @($rows | Where-Object { $_.kind -eq 'sample' })
$errors = [System.Collections.Generic.List[string]]::new()
if ($starts.Count -ne 1) { $errors.Add("expected one start row, got $($starts.Count)") }
if ($samples.Count -eq 0) { $errors.Add('no samples') }

$start = if ($starts.Count -gt 0) { $starts[0] } else { $null }
if ($start) {
    if ($start.pid -ne $ExpectedPid) { $errors.Add('start PID mismatch') }
    if ($start.executable -ne $ExpectedExe) { $errors.Add('start executable mismatch') }
    if ($start.sha256 -ne $ExpectedHash) { $errors.Add('start hash mismatch') }
    if ($start.interval_seconds -ne 60) { $errors.Add('unexpected sample interval') }
}

$previousTime = if ($start) { Parse-Utc $start.utc } else { $null }
$previousVersion = $null
$maximumObservedGap = 0.0
$expectedSample = 0
foreach ($sample in $samples) {
    $expectedSample++
    $n = [int]$sample.sample
    $time = Parse-Utc $sample.utc
    if ($n -ne $expectedSample) { $errors.Add("sample number gap at $n") }
    if ($sample.pid -ne $ExpectedPid) { $errors.Add("PID mismatch at sample $n") }
    if ($sample.process_alive -ne $true) { $errors.Add("process missing at sample $n") }
    if ($sample.safety_allowed -ne $true) { $errors.Add("safety blocked at sample $n") }
    if ($sample.lease_owned -ne $true) { $errors.Add("lease not owned at sample $n") }
    if ($sample.reason_code) { $errors.Add("reason code at sample $n") }
    if ($sample.bot_running -ne $false) { $errors.Add("bot not stopped at sample $n") }
    if ($sample.open_offers -ne 0) { $errors.Add("open offers at sample $n") }
    if ($sample.sage_wallet_sync -ne 'synced') { $errors.Add("wallet not synced at sample $n") }
    if ($sample.safety_error -or $sample.health_error -or $sample.offers_error) {
        $errors.Add("API read error at sample $n")
    }
    if (-not $sample.lease_expires_at -or (Parse-Utc $sample.lease_expires_at) -le $time) {
        $errors.Add("lease expired at sample $n")
    }
    if ($null -ne $previousVersion -and $sample.lease_version -le $previousVersion) {
        $errors.Add("lease version did not advance at sample $n")
    }
    $previousVersion = $sample.lease_version
    if ($previousTime) {
        $gap = ($time - $previousTime).TotalSeconds
        $maximumObservedGap = [math]::Max($maximumObservedGap, $gap)
        if ($gap -le 0 -or $gap -gt $MaximumGapSeconds) {
            $errors.Add("observation gap $([math]::Round($gap, 3)) seconds at sample $n")
        }
    }
    $previousTime = $time
}

$durationHours = if ($start -and $samples.Count -gt 0) {
    ($previousTime - (Parse-Utc $start.utc)).TotalHours
} else { 0.0 }

$process = Get-CimInstance Win32_Process -Filter "ProcessId=$ExpectedPid"
if (-not $process -or $process.Name -ne 'Catalyst.exe' -or $process.ExecutablePath -ne $ExpectedExe) {
    $errors.Add('current exact process missing')
} else {
    $actualHash = (Get-FileHash -LiteralPath $process.ExecutablePath -Algorithm SHA256).Hash
    if ($actualHash -ne $ExpectedHash) { $errors.Add('current executable hash mismatch') }
}
$listeners = @(Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -ne 1 -or $listeners[0].OwningProcess -ne $ExpectedPid) {
    $errors.Add('port 5000 does not have one exact owner')
}

$result = [ordered]@{
    start_utc = if ($start) { $start.utc } else { $null }
    last_sample_utc = if ($samples.Count -gt 0) { $samples[-1].utc } else { $null }
    samples = $samples.Count
    duration_hours = [math]::Round($durationHours, 6)
    maximum_gap_seconds = [math]::Round($maximumObservedGap, 3)
    errors = @($errors)
    complete = ($durationHours -ge $RequiredHours -and $errors.Count -eq 0)
}
$result | ConvertTo-Json -Depth 5
if ($errors.Count -gt 0) { exit 1 }
if ($durationHours -lt $RequiredHours) { exit 2 }
exit 0
