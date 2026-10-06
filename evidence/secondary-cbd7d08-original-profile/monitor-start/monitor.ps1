param(
    [int]$TargetPid = 5656,
    [string]$ExpectedExe = 'C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\acceptance-cbd7d08-20261006T0320BST\extracted\Catalyst\Catalyst.exe',
    [string]$ExpectedHash = 'DBC3D205070D58E6C443FDC2C4BE28CE4B106359BAE285C31A87C70FBDA0AE26'
)

$ErrorActionPreference = 'Stop'
$monitorRoot = 'C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\monitor-cbd7d08-20261006T034000BST'
$tracePath = Join-Path $monitorRoot 'trace-60s.jsonl'
$alertPath = Join-Path $monitorRoot 'alerts.jsonl'
$summaryPath = Join-Path $monitorRoot 'summary.json'
$sageProbe = 'C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\monitor-cbd7d08-20261006T034000BST\sage_readonly.py'
$profileRoot = 'C:\Users\M920q\AppData\Roaming\Catalyst'
$baseUri = 'http://127.0.0.1:5000'
$deadline = (Get-Date).ToUniversalTime().AddHours(24)
$expectedFingerprint = 3702373391
$expectedWalletId = 2
$expectedAsset = 'b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105'
$expectedCampaign = 'd61791de6807761e4a81c2a3ce58fb7b2ebad2dd012593ba0a37a122198694d5'
$expectedXch = '240.800676512155'
$expectedMz = '3381521.72'

function Write-JsonLine([string]$Path, [hashtable]$Record) {
    $Record | ConvertTo-Json -Depth 12 -Compress | Add-Content -LiteralPath $Path -Encoding utf8
}

function Get-Sha256([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            return ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '')
        } finally {
            $sha.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

function Get-ProfileHashes {
    $result = @{}
    foreach ($name in @('.env', 'bot.db', 'bot.db-wal', 'bot.db-shm')) {
        $path = Join-Path $profileRoot $name
        if (Test-Path -LiteralPath $path) {
            try {
                $result[$name] = Get-Sha256 $path
            } catch {
                $result[$name] = 'LOCKED:' + $_.Exception.GetType().Name
            }
        } else {
            $result[$name] = 'MISSING'
        }
    }
    return $result
}

$process = Get-Process -Id $TargetPid -ErrorAction Stop
if ($process.ProcessName -ne 'Catalyst') {
    throw 'Target PID is not Catalyst.exe.'
}
$actualExe = $process.Path
if (-not [string]::Equals($actualExe, $ExpectedExe, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Executable path mismatch: $actualExe"
}
$actualHash = Get-Sha256 $actualExe
if ($actualHash -ne $ExpectedHash) {
    throw "Executable hash mismatch: $actualHash"
}

$startRecord = @{
    kind = 'start'
    utc = (Get-Date).ToUniversalTime().ToString('o')
    target_end_utc = $deadline.ToString('o')
    interval_seconds = 60
    pid = $TargetPid
    executable = $actualExe
    sha256 = $actualHash
    source_commit = 'cbd7d08e3efb99ee449efc5d5b3da2c6381f0d31'
    scope = 'read-only exact-candidate stopped-profile stability monitor'
    expected_identity = @{
        fingerprint = $expectedFingerprint
        network = 'mainnet'
        wallet_id = $expectedWalletId
        asset_id = $expectedAsset
    }
    profile_hashes = Get-ProfileHashes
}
Write-JsonLine $tracePath $startRecord

$sample = 0
$alertCount = 0
while ((Get-Date).ToUniversalTime() -lt $deadline) {
    $sample++
    $record = @{
        kind = 'sample'
        sample = $sample
        utc = (Get-Date).ToUniversalTime().ToString('o')
        pid = $TargetPid
        alerts = @()
    }

    try {
        $allCatalyst = @(Get-Process Catalyst -ErrorAction SilentlyContinue)
        $target = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
        $record.catalyst_process_count = $allCatalyst.Count
        $record.process_alive = $null -ne $target
        if ($null -eq $target) {
            $record.alerts += 'expected_process_not_running'
            Write-JsonLine $tracePath $record
            Write-JsonLine $alertPath $record
            $alertCount++
            break
        }
        $record.executable = $target.Path
        if (-not [string]::Equals($target.Path, $ExpectedExe, [StringComparison]::OrdinalIgnoreCase)) {
            $record.alerts += 'executable_path_mismatch'
        }
        if ($allCatalyst.Count -ne 1) {
            $record.alerts += 'unexpected_catalyst_process_count'
        }
        if ($sample -eq 1 -or ($sample % 60) -eq 0) {
            $record.exe_sha256 = Get-Sha256 $target.Path
            if ($record.exe_sha256 -ne $ExpectedHash) {
                $record.alerts += 'executable_hash_mismatch'
            }
        }

        $listener = @(Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue)
        $record.port_5000_listener_count = $listener.Count
        $record.port_5000_owner = if ($listener.Count -eq 1) { $listener[0].OwningProcess } else { $null }
        if ($listener.Count -ne 1 -or $record.port_5000_owner -ne $TargetPid) {
            $record.alerts += 'port_5000_owner_mismatch'
        }

        $watch = [Diagnostics.Stopwatch]::StartNew()
        $health = Invoke-RestMethod ($baseUri + '/api/health') -TimeoutSec 10
        $status = Invoke-RestMethod ($baseUri + '/api/status') -TimeoutSec 20
        $fingerprint = Invoke-RestMethod ($baseUri + '/api/fingerprint') -TimeoutSec 10
        $offers = Invoke-RestMethod ($baseUri + '/api/offers') -TimeoutSec 15
        $bootstrap = Invoke-RestMethod ($baseUri + '/api/bootstrap/status') -TimeoutSec 15
        $coinPrep = Invoke-RestMethod ($baseUri + '/api/coin-prep/status') -TimeoutSec 15
        $reservations = Invoke-RestMethod ($baseUri + '/api/reservations') -TimeoutSec 15
        $safety = Invoke-RestMethod ($baseUri + '/api/safety/status') -TimeoutSec 10
        $watch.Stop()

        $record.api_latency_ms = $watch.ElapsedMilliseconds
        $record.health = $health.status
        $record.bot_running = [bool]$status.running
        $record.wallet_synced = [bool]$status.chia_health.wallet_synced
        $record.fingerprint = [int64]$fingerprint.fingerprint
        $record.network = [string]$bootstrap.identity.network
        $record.wallet_id = [int]$status.current_cat.wallet_id
        $record.asset_id = [string]$status.current_cat.asset_id
        $record.xch = [string]$status.balances.xch.total
        $record.mz = [string]$status.balances.cat.total
        $record.buy_offers = [int]$offers.buy_count
        $record.sell_offers = [int]$offers.sell_count
        $record.xch_locked = [int]$status.coin_tracking.xch_locked
        $record.mz_locked = [int]$status.coin_tracking.cat_locked
        $record.safety_allowed = [bool]$safety.safety.allowed
        $record.safety_reason = [string]$safety.safety.reason_code
        $record.lease_owned = [bool]$safety.safety.lease.owned_by_this_run
        $record.lease_version = [int64]$safety.safety.lease.version
        $record.lease_expires_at = [string]$safety.safety.lease.expires_at
        $record.campaign_id = [string]$bootstrap.campaign.campaign_id
        $record.campaign_status = [string]$bootstrap.campaign.status
        $record.campaign_expired = [bool]$bootstrap.campaign.expired
        $record.campaign_cancel_required = [bool]$bootstrap.campaign.cancel_required
        $record.campaign_fee_spent_xch = [string]$bootstrap.campaign.fee_spent_xch
        $record.fee_approval_id = [string]$coinPrep.fee_approval.approval_id
        $record.fee_held_mojos = [string]$coinPrep.fee_approval.held_fee_mojos
        $record.fee_unresolved = [int]$coinPrep.fee_approval.unresolved_operation_count
        $record.fee_dispatch_authorized = [bool]$coinPrep.fee_approval.dispatch_authorized
        $record.coin_prep_running = [bool]$coinPrep.running
        $record.reservations = [int]$reservations.totals.count

        if ($record.health -ne 'ok') { $record.alerts += 'health_not_ok' }
        if ($record.bot_running) { $record.alerts += 'bot_started' }
        if (-not $record.wallet_synced) { $record.alerts += 'wallet_not_synced' }
        if ($record.fingerprint -ne $expectedFingerprint) { $record.alerts += 'fingerprint_mismatch' }
        if ($record.network -ne 'mainnet') { $record.alerts += 'network_mismatch' }
        if ($record.wallet_id -ne $expectedWalletId) { $record.alerts += 'wallet_id_mismatch' }
        if ($record.asset_id -ne $expectedAsset) { $record.alerts += 'asset_id_mismatch' }
        if ($record.xch -ne $expectedXch) { $record.alerts += 'xch_balance_changed' }
        if ($record.mz -ne $expectedMz) { $record.alerts += 'mz_balance_changed' }
        if (($record.buy_offers + $record.sell_offers) -ne 0) { $record.alerts += 'active_offers_detected' }
        if (($record.xch_locked + $record.mz_locked) -ne 0) { $record.alerts += 'locked_coins_detected' }
        if (-not $record.safety_allowed) { $record.alerts += 'safety_blocked' }
        if (-not $record.lease_owned) { $record.alerts += 'lease_not_owned' }
        if ($record.campaign_id -ne $expectedCampaign) { $record.alerts += 'campaign_changed' }
        if (-not $record.campaign_expired -or -not $record.campaign_cancel_required) { $record.alerts += 'campaign_guard_changed' }
        if ($record.fee_held_mojos -ne '0') { $record.alerts += 'fee_hold_detected' }
        if ($record.fee_unresolved -ne 0) { $record.alerts += 'unresolved_fee_operation' }
        if ($record.fee_dispatch_authorized) { $record.alerts += 'fee_dispatch_authorized' }
        if ($record.coin_prep_running) { $record.alerts += 'coin_prep_started' }
        if ($record.reservations -ne 0) { $record.alerts += 'reservation_detected' }

        if ($sample -eq 1 -or ($sample % 15) -eq 0) {
            $sageRaw = & py -3.14 $sageProbe 2>&1 | Out-String
            $sage = $sageRaw | ConvertFrom-Json
            $record.sage = @{
                fingerprint = [int64]$sage.key.key.fingerprint
                network = [string]$sage.key.key.network_id
                pending_count = [int]$sage.pending_count
                fillable_count = [int]$sage.fillable_count
                offer_total = [int]$sage.offer_total
                selectable_balance = [string]$sage.sync.selectable_balance
            }
            if ($record.sage.fingerprint -ne $expectedFingerprint) { $record.alerts += 'sage_fingerprint_mismatch' }
            if ($record.sage.network -ne 'mainnet') { $record.alerts += 'sage_network_mismatch' }
            if ($record.sage.pending_count -ne 0) { $record.alerts += 'sage_pending_transactions' }
            if ($record.sage.fillable_count -ne 0) { $record.alerts += 'sage_fillable_offers' }
        }
    } catch {
        $record.error = $_.Exception.GetType().Name + ': ' + $_.Exception.Message
        $record.alerts += 'sample_exception'
    }

    if ($record.alerts.Count -gt 0) {
        $alertCount++
        Write-JsonLine $alertPath $record
    }
    Write-JsonLine $tracePath $record
    Start-Sleep -Seconds 60
}

$endRecord = @{
    kind = 'end'
    utc = (Get-Date).ToUniversalTime().ToString('o')
    samples = $sample
    alerts = $alertCount
    profile_hashes = Get-ProfileHashes
}
Write-JsonLine $tracePath $endRecord
$endRecord | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding utf8
