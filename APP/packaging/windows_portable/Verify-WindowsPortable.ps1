[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$PortableRoot,
  [Parameter(Mandatory=$true)][string]$EvidenceRoot
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PortableRoot = (Resolve-Path $PortableRoot).Path
$Exe = Join-Path $PortableRoot "Tianxia Factory.exe"
$AcceptanceData = Join-Path ([IO.Path]::GetTempPath()) ("Tianxia Factory W5 Acceptance Ω " + $PID)
$StateFile = Join-Path $AcceptanceData "Logs\launcher_state.json"
$LogFile = Join-Path $AcceptanceData "Logs\Tianxia_Factory_Launcher.log"
$BrowserSentinel = Join-Path $EvidenceRoot "unexpected-browser-launch.txt"
$BrowserNames = @("chrome", "msedge", "firefox", "brave", "opera", "iexplore")
New-Item -ItemType Directory -Force $EvidenceRoot | Out-Null
if ($PortableRoot -notmatch ' ') { throw "Acceptance root must contain a space." }
if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw "Tianxia Factory.exe is missing." }
$CatalogAuthority = Join-Path $PortableRoot "Runtime\catalog_authority\cat3\generated\catalog_authority.v1.json"
$SphereTalentUiLogic = Join-Path $PortableRoot "Runtime\static\sphere_talent_logic.js"
$GmScreenAuthority = Join-Path $PortableRoot "Runtime\gm_screen\HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip"
if (-not (Test-Path -LiteralPath $CatalogAuthority -PathType Leaf)) { throw "Required catalog authority data is missing: $CatalogAuthority" }
if (-not (Test-Path -LiteralPath $SphereTalentUiLogic -PathType Leaf)) { throw "Required Sphere/Talent UI data is missing: $SphereTalentUiLogic" }
if (-not (Test-Path -LiteralPath $GmScreenAuthority -PathType Leaf)) { throw "Required GM Screen authority is missing: $GmScreenAuthority" }

function Get-NormalBrowserSnapshot {
  $items = @()
  foreach ($name in $BrowserNames) {
    $items += @(Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
      [PSCustomObject]@{ name=$_.ProcessName; id=$_.Id; start_time=try{$_.StartTime.ToUniversalTime().ToString('o')}catch{$null} }
    })
  }
  return @($items)
}

function Wait-FactoryReady([System.Diagnostics.Process]$Process, [int]$Minutes) {
  $deadline = [DateTime]::UtcNow.AddMinutes($Minutes)
  $state = $null
  while ([DateTime]::UtcNow -lt $deadline) {
    $Process.Refresh()
    if ($Process.HasExited) { throw "Factory exited before becoming ready (exit code $($Process.ExitCode))." }
    if (Test-Path -LiteralPath $StateFile) {
      try { $state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json } catch { $state = $null }
      if ($null -ne $state) {
        if ($state.state -eq "FAILED") {
          Copy-Item -LiteralPath $StateFile -Destination (Join-Path $EvidenceRoot "failed-launcher-state.json") -Force -ErrorAction SilentlyContinue
          Copy-Item -LiteralPath $LogFile -Destination (Join-Path $EvidenceRoot "failed-startup.log") -Force -ErrorAction SilentlyContinue
          throw "Factory reported failure. See $LogFile"
        }
        if ($state.url -and $state.state -in @("RUNNING", "WINDOW_READY")) { return $state }
      }
    }
    Start-Sleep -Milliseconds 400
  }
  throw "Factory did not become ready within $Minutes minutes."
}

function Wait-DedicatedWindow([System.Diagnostics.Process]$Process) {
  $deadline = [DateTime]::UtcNow.AddSeconds(45)
  while ([DateTime]::UtcNow -lt $deadline) {
    $Process.Refresh()
    if ($Process.HasExited) { throw "Factory exited before its dedicated window was observable." }
    if ($Process.MainWindowHandle -ne 0 -and $Process.MainWindowTitle -eq "Tianxia Factory") {
      return [PSCustomObject]@{ handle=$Process.MainWindowHandle.ToInt64(); title=$Process.MainWindowTitle }
    }
    Start-Sleep -Milliseconds 250
  }
  throw "A dedicated window titled 'Tianxia Factory' was not observable."
}

function Assert-StateContract($State) {
  if ($State.window_title -ne "Tianxia Factory") { throw "State did not identify the dedicated Tianxia Factory window." }
  if ($State.window_host -ne "pywebview-edgechromium") { throw "State did not identify the WebView2 desktop host." }
  if ($State.renderer -ne "edgechromium") { throw "State did not identify the Edge Chromium renderer." }
  if ($State.default_browser_launch_attempted -ne $false) { throw "Normal startup reported a default-browser launch attempt." }
  if ([int]$State.external_navigation_count -ne 0) { throw "Normal startup unexpectedly requested external navigation." }
  if (-not $State.webview2_runtime_version -or $State.webview2_runtime_version -eq "0.0.0.0") { throw "WebView2 Runtime identity was not recorded." }
  $uri = [Uri]$State.url
  if ($uri.Scheme -ne "http" -or $uri.Host -ne "127.0.0.1") { throw "Factory service is not bound to the expected loopback URL." }
}

function Assert-NoNewNormalBrowser($Before) {
  $beforeIds = @($Before | ForEach-Object { [int]$_.id })
  $after = @(Get-NormalBrowserSnapshot)
  $new = @($after | Where-Object { [int]$_.id -notin $beforeIds })
  if ($new.Count -gt 0) {
    $new | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $EvidenceRoot "unexpected-normal-browser-processes.json") -Encoding UTF8
    throw "Normal startup created a regular browser process."
  }
  return $after
}

function Assert-NoOwnedProcess([int]$OriginalPid) {
  Start-Sleep -Milliseconds 800
  if (Get-Process -Id $OriginalPid -ErrorAction SilentlyContinue) { throw "Tianxia Factory process remained after close." }
  $sameExe = @(Get-Process -Name "Tianxia Factory" -ErrorAction SilentlyContinue | Where-Object {
    try { $_.Path -eq $Exe } catch { $false }
  })
  if ($sameExe.Count -gt 0) { throw "An orphaned Tianxia Factory process remained after close." }
}

function Assert-ServiceStopped([string]$Url) {
  Start-Sleep -Milliseconds 500
  try {
    Invoke-WebRequest -Uri $Url -TimeoutSec 2 | Out-Null
    throw "Local service remained reachable after Factory exit."
  } catch {
    if ($_.Exception.Message -eq "Local service remained reachable after Factory exit.") { throw }
  }
}

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class TianxiaWinClose {
  [DllImport("user32.dll")]
  public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
}
'@

function Close-Factory([System.Diagnostics.Process]$Process, [string]$Url) {
  $Process.Refresh()
  if ($Process.MainWindowHandle -eq 0) { throw "Dedicated Factory window was not available for close." }
  [TianxiaWinClose]::PostMessage($Process.MainWindowHandle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
  if (-not $Process.WaitForExit(45000)) { throw "Factory did not exit cleanly after the window was closed." }
  Assert-NoOwnedProcess $Process.Id
  Assert-ServiceStopped $Url
}

$Process = $null
$Process2 = $null
$PriorSentinel = $env:TIANXIA_BROWSER_LAUNCH_SENTINEL
$PriorDataRoot = $env:TIANXIA_FOUNDRY_DATA
try {
  Remove-Item -LiteralPath $AcceptanceData -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force $AcceptanceData | Out-Null
  $env:TIANXIA_FOUNDRY_DATA = $AcceptanceData
  Remove-Item -LiteralPath $StateFile,$BrowserSentinel -Force -ErrorAction SilentlyContinue
  $env:TIANXIA_BROWSER_LAUNCH_SENTINEL = $BrowserSentinel
  $browserBefore = @(Get-NormalBrowserSnapshot)

  # Cycle 1: open dedicated window, reach loopback service, create/read a project, close cleanly.
  $Process = Start-Process -FilePath $Exe -WorkingDirectory $PortableRoot -PassThru
  $state = Wait-FactoryReady $Process 4
  Assert-StateContract $state
  $window = Wait-DedicatedWindow $Process
  # Defer browser assertions until after the Factory has closed cleanly. If an
  # unrelated browser process appears during acceptance, evidence still fails,
  # but the dedicated WebView2 host is not force-terminated by the finally block.
  $browserAfter = @(Get-NormalBrowserSnapshot)

  $session = Invoke-RestMethod -Uri ($state.url + "api/session") -Method Get
  $headers = @{ "X-Foundry-Token" = $session.token }
  $health = Invoke-RestMethod -Uri ($state.url + "api/health") -Method Get -Headers $headers
  $version = Invoke-RestMethod -Uri ($state.url + "api/version") -Method Get -Headers $headers
  $packs = Invoke-RestMethod -Uri ($state.url + "api/content-packs") -Method Get -Headers $headers
  $core = $packs | Where-Object { $_.pack_id -eq "tianxia.core" -or $_.pack_id -eq "core" } | Select-Object -First 1
  if (-not $core) { $core = $packs | Select-Object -First 1 }
  if (-not $core) { throw "No installed content pack is available for project creation." }
  $body = @{ working_name="W5 Desktop Window Acceptance Project"; quality_target="rival/boss"; pack_locks=@(@{pack_id=$core.pack_id;version=$core.version}) } | ConvertTo-Json -Depth 5
  $project = Invoke-RestMethod -Uri ($state.url + "api/projects") -Method Post -Headers $headers -ContentType "application/json" -Body $body
  $projects = Invoke-RestMethod -Uri ($state.url + "api/projects") -Method Get -Headers $headers
  if (-not ($projects | Where-Object { $_.project_id -eq $project.project_id })) { throw "Created project was not readable through the packaged app." }
  Close-Factory $Process $state.url
  $browserAfter = Assert-NoNewNormalBrowser $browserBefore
  if (Test-Path -LiteralPath $BrowserSentinel) { throw "Normal startup reached the system-browser launch path." }

  # Cycle 2: reopen, prove project persistence, then close cleanly again.
  Remove-Item -LiteralPath $StateFile,$BrowserSentinel -Force -ErrorAction SilentlyContinue
  $browserBefore2 = @(Get-NormalBrowserSnapshot)
  $Process2 = Start-Process -FilePath $Exe -WorkingDirectory $PortableRoot -PassThru
  $state2 = Wait-FactoryReady $Process2 3
  Assert-StateContract $state2
  $window2 = Wait-DedicatedWindow $Process2
  $browserAfter2 = @(Get-NormalBrowserSnapshot)
  $session2 = Invoke-RestMethod -Uri ($state2.url + "api/session") -Method Get
  $projects2 = Invoke-RestMethod -Uri ($state2.url + "api/projects") -Method Get -Headers @{"X-Foundry-Token"=$session2.token}
  if (-not ($projects2 | Where-Object { $_.project_id -eq $project.project_id })) { throw "Project did not persist across restart." }
  Close-Factory $Process2 $state2.url
  $browserAfter2 = Assert-NoNewNormalBrowser $browserBefore2
  if (Test-Path -LiteralPath $BrowserSentinel) { throw "Second startup reached the system-browser launch path." }

  $secretPatterns = 'session_token|api[_-]?key|BEGIN PRIVATE KEY|TIANXIA_INTEGRITY_KEY'
  if (Test-Path -LiteralPath $LogFile) {
    if (Select-String -LiteralPath $LogFile -Pattern $secretPatterns -Quiet) { throw "Known secret pattern found in launcher log." }
  }

  $browserEvidence = [ordered]@{
    status = "PASS"
    startup_1_baseline = $browserBefore
    startup_1_after = $browserAfter
    startup_2_baseline = $browserBefore2
    startup_2_after = $browserAfter2
    normal_browser_process_created = $false
    browser_launch_sentinel_created = $false
  }
  $browserEvidence | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $EvidenceRoot "default-browser-observation.json") -Encoding UTF8

  $result = [ordered]@{
    status = "PASS"
    scope = "W5-P1 current native Windows desktop-window and isolated writable-data acceptance"
    window_title = $window.title
    second_window_title = $window2.title
    window_host = $state.window_host
    renderer = $state.renderer
    webview2_runtime_version = $state.webview2_runtime_version
    default_browser_not_launched = $true
    loopback_health_ready = $true
    loopback_url = $state.url
    project_created_and_read = $true
    project_id = $project.project_id
    shutdown_clean = $true
    no_orphan_factory_process = $true
    persistence_across_restart = $true
    second_cycle_passed = $true
    secret_pattern_scan = "PASS"
    manual_owner_check_remaining = "Confirm visually that the dedicated window has no browser tabs, address bar, favorites bar, or other normal browser chrome."
    version = $version
    health = $health
    writable_data_root = $AcceptanceData
    writable_data_root_has_space = $AcceptanceData.Contains(" ")
    writable_data_root_has_non_ascii = ($AcceptanceData.ToCharArray() | Where-Object { [int]$_ -gt 127 }).Count -gt 0
    completed_at_utc = [DateTime]::UtcNow.ToString('o')
  }
  $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $EvidenceRoot "windows-desktop-window-acceptance.json") -Encoding UTF8
  @(
    "MANUAL OWNER CHECK STILL REQUIRED",
    "Open Tianxia Factory.exe and confirm the dedicated Tianxia Factory window has no browser tabs, address bar, favorites bar, or ordinary browser chrome.",
    "All process, loopback, project, persistence, close, and default-browser observations are automated by this acceptance script."
  ) | Set-Content -LiteralPath (Join-Path $EvidenceRoot "manual-owner-check-required.txt") -Encoding UTF8
  Copy-Item -LiteralPath $LogFile -Destination (Join-Path $EvidenceRoot "startup-shutdown.log") -ErrorAction SilentlyContinue
  Write-Host "WINDOWS DESKTOP-WINDOW ACCEPTANCE PASS"
} finally {
  if ($null -eq $PriorDataRoot) { Remove-Item Env:TIANXIA_FOUNDRY_DATA -ErrorAction SilentlyContinue }
  else { $env:TIANXIA_FOUNDRY_DATA = $PriorDataRoot }
  foreach ($Candidate in @($Process, $Process2)) {
    if ($null -ne $Candidate) {
      try {
        $Candidate.Refresh()
        if (-not $Candidate.HasExited) { Stop-Process -Id $Candidate.Id -Force -ErrorAction SilentlyContinue }
      } catch {}
    }
  }
  Remove-Item -LiteralPath $AcceptanceData -Recurse -Force -ErrorAction SilentlyContinue
  if ($null -eq $PriorSentinel) { Remove-Item Env:TIANXIA_BROWSER_LAUNCH_SENTINEL -ErrorAction SilentlyContinue }
  else { $env:TIANXIA_BROWSER_LAUNCH_SENTINEL = $PriorSentinel }
}
