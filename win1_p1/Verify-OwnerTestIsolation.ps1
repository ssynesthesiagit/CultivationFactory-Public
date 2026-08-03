[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$DeliveryRoot,
  [Parameter(Mandatory=$true)][string]$EvidenceRoot
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Sha256([string]$Path) {
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-TreeIdentity([string]$Root) {
  $Root = [IO.Path]::GetFullPath($Root).TrimEnd('\')
  $Rows = @(Get-ChildItem -LiteralPath $Root -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
    "$($_.FullName.Substring($Root.Length + 1).Replace('\','/'))|$($_.Length)|$(Sha256 $_.FullName)"
  })
  $Text = ($Rows -join "`n") + "`n"
  $Bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
  $Hasher = [Security.Cryptography.SHA256]::Create()
  try { $Commitment = ([BitConverter]::ToString($Hasher.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant() }
  finally { $Hasher.Dispose() }
  return [ordered]@{
    file_count = $Rows.Count
    total_bytes = [long](Get-ChildItem -LiteralPath $Root -Recurse -File -Force | Measure-Object -Property Length -Sum).Sum
    tree_sha256 = $Commitment
  }
}

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class Win1P1Close {
  [DllImport("user32.dll")]
  public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
}
'@

function Invoke-IsolatedLaunch {
  param(
    [string]$Launcher,
    [string]$DataRoot,
    [string]$ExpectedTitle,
    [string]$EvidenceName
  )
  if (Test-Path -LiteralPath $DataRoot) { Remove-Item -LiteralPath $DataRoot -Recurse -Force }
  $StateFile = Join-Path $DataRoot "Logs\launcher_state.json"
  $Cmd = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d','/c',('"{0}"' -f $Launcher)) -WorkingDirectory $DeliveryRoot -PassThru -WindowStyle Hidden
  $State = $null
  $Factory = $null
  try {
    $Deadline = [DateTime]::UtcNow.AddMinutes(8)
    while ([DateTime]::UtcNow -lt $Deadline) {
      if (Test-Path -LiteralPath $StateFile) {
        try { $State = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json } catch { $State = $null }
        if ($null -ne $State -and $State.state -eq 'FAILED') { throw "Owner-test launcher reported FAILED: $($State.error)" }
        if ($null -ne $State -and $State.url -and $State.state -in @('RUNNING','WINDOW_READY')) { break }
      }
      if ($Cmd.HasExited) { throw "Owner-test launcher exited before publishing a ready state (exit $($Cmd.ExitCode))." }
      Start-Sleep -Milliseconds 500
    }
    if ($null -eq $State -or -not $State.url) { throw "Owner-test launcher did not become ready within eight minutes." }
    if ($State.window_title -ne $ExpectedTitle) { throw "Owner-test title mismatch: $($State.window_title)" }
    $ExpectedData = [IO.Path]::GetFullPath($DataRoot).TrimEnd('\')
    $ReportedLog = [IO.Path]::GetFullPath([string]$State.log)
    if (-not $ReportedLog.StartsWith($ExpectedData + '\', [StringComparison]::OrdinalIgnoreCase)) {
      throw "Launcher log escaped the expected isolated data root: $ReportedLog"
    }
    $Factory = Get-Process -Id ([int]$State.pid) -ErrorAction Stop
    $WindowDeadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $WindowDeadline -and $Factory.MainWindowHandle -eq 0) {
      Start-Sleep -Milliseconds 250
      $Factory.Refresh()
    }
    if ($Factory.MainWindowHandle -eq 0 -or $Factory.MainWindowTitle -ne $ExpectedTitle) {
      throw "The visibly labeled owner-test window was not observable."
    }
    $Session = Invoke-RestMethod -Uri ($State.url + 'api/session') -Method Get -TimeoutSec 30
    $Health = Invoke-RestMethod -Uri ($State.url + 'api/health') -Method Get -Headers @{'X-Foundry-Token'=$Session.token} -TimeoutSec 30
    [Win1P1Close]::PostMessage($Factory.MainWindowHandle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
    if (-not $Factory.WaitForExit(45000)) { throw "Owner-test application did not close cleanly." }
    if (-not $Cmd.WaitForExit(15000)) { throw "Owner-test launcher did not finish after application close." }
    $Record = [ordered]@{
      status = 'PASS'
      launcher = [IO.Path]::GetFileName($Launcher)
      expected_data_root = $ExpectedData
      reported_log = $ReportedLog
      window_title = $State.window_title
      window_host = $State.window_host
      renderer = $State.renderer
      loopback_url = $State.url
      health = $Health
      clean_shutdown = $true
    }
    $Record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $EvidenceRoot "$EvidenceName.json") -Encoding UTF8
    Copy-Item -LiteralPath $StateFile -Destination (Join-Path $EvidenceRoot "$EvidenceName-launcher-state.json") -Force
    $LogFile = Join-Path $DataRoot "Logs\Tianxia_Factory_Launcher.log"
    if (Test-Path -LiteralPath $LogFile) { Copy-Item -LiteralPath $LogFile -Destination (Join-Path $EvidenceRoot "$EvidenceName-startup.log") -Force }
    return $Record
  } finally {
    if ($null -ne $Factory) {
      try { $Factory.Refresh(); if (-not $Factory.HasExited) { Stop-Process -Id $Factory.Id -Force } } catch {}
    }
    try { if (-not $Cmd.HasExited) { Stop-Process -Id $Cmd.Id -Force } } catch {}
  }
}

$DeliveryRoot = [IO.Path]::GetFullPath($DeliveryRoot).TrimEnd('\')
$EvidenceRoot = [IO.Path]::GetFullPath($EvidenceRoot).TrimEnd('\')
New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$ApplicationRoot = Join-Path $DeliveryRoot 'Application'
$OwnerRoot = Join-Path $DeliveryRoot 'OwnerTestData'
$PrimaryRoot = $OwnerRoot
$CleanRoot = Join-Path $OwnerRoot 'CleanFactory'
if (Test-Path -LiteralPath (Join-Path $ApplicationRoot 'UserData')) {
  throw "Delivery contains an internal UserData directory; isolation must fail closed."
}

$Sandbox = Join-Path ([IO.Path]::GetTempPath()) ("Tianxia-WIN1-P1-Isolation-" + [guid]::NewGuid().ToString('N'))
$FakeLocalAppData = Join-Path $Sandbox 'LocalAppData'
$ProductionData = Join-Path $FakeLocalAppData 'Tianxia Factory'
$ExistingInstall = Join-Path $Sandbox 'Existing Tianxia Installation'
New-Item -ItemType Directory -Force -Path $ProductionData,$ExistingInstall | Out-Null
[IO.File]::WriteAllText((Join-Path $ProductionData 'production-canary.txt'), 'PRODUCTION USERDATA MUST REMAIN UNCHANGED', [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText((Join-Path $ExistingInstall 'installation-canary.txt'), 'EXISTING INSTALLATION MUST REMAIN UNCHANGED', [Text.UTF8Encoding]::new($false))
$ProductionBefore = Get-TreeIdentity $ProductionData
$InstallationBefore = Get-TreeIdentity $ExistingInstall
$ApplicationBefore = Get-TreeIdentity $ApplicationRoot
$PriorLocalAppData = $env:LOCALAPPDATA
$PriorData = $env:TIANXIA_FOUNDRY_DATA
$PriorTitle = $env:TIANXIA_WINDOW_TITLE
try {
  $env:LOCALAPPDATA = $FakeLocalAppData
  Remove-Item Env:TIANXIA_FOUNDRY_DATA -ErrorAction SilentlyContinue
  Remove-Item Env:TIANXIA_WINDOW_TITLE -ErrorAction SilentlyContinue
  $Primary = Invoke-IsolatedLaunch -Launcher (Join-Path $DeliveryRoot 'LAUNCH_TIANXIA_OWNER_TEST.cmd') -DataRoot $PrimaryRoot -ExpectedTitle 'Tianxia WIN1-P1 Owner Test' -EvidenceName 'primary-owner-test-launch'
  $Clean = Invoke-IsolatedLaunch -Launcher (Join-Path $DeliveryRoot 'LAUNCH_CLEAN_IMPORT_TEST.cmd') -DataRoot $CleanRoot -ExpectedTitle 'Tianxia WIN1-P1 Clean Import Test' -EvidenceName 'clean-import-launch'
} finally {
  if ($null -eq $PriorLocalAppData) { Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue } else { $env:LOCALAPPDATA = $PriorLocalAppData }
  if ($null -eq $PriorData) { Remove-Item Env:TIANXIA_FOUNDRY_DATA -ErrorAction SilentlyContinue } else { $env:TIANXIA_FOUNDRY_DATA = $PriorData }
  if ($null -eq $PriorTitle) { Remove-Item Env:TIANXIA_WINDOW_TITLE -ErrorAction SilentlyContinue } else { $env:TIANXIA_WINDOW_TITLE = $PriorTitle }
}
$ProductionAfter = Get-TreeIdentity $ProductionData
$InstallationAfter = Get-TreeIdentity $ExistingInstall
$ApplicationAfter = Get-TreeIdentity $ApplicationRoot
$Preserved = ($ProductionBefore.tree_sha256 -eq $ProductionAfter.tree_sha256) -and
  ($InstallationBefore.tree_sha256 -eq $InstallationAfter.tree_sha256) -and
  ($ApplicationBefore.tree_sha256 -eq $ApplicationAfter.tree_sha256)
if (-not $Preserved) { throw "Isolation proof detected a production-data, existing-installation, or application-payload change." }

[ordered]@{
  schema = 'Tianxia.WIN1P1.IsolationProof.v1'
  status = 'PASS'
  primary_data_root = [IO.Path]::GetFullPath($PrimaryRoot)
  clean_factory_data_root = [IO.Path]::GetFullPath($CleanRoot)
  owner_test_base = [IO.Path]::GetFullPath($OwnerRoot)
  production_localappdata_candidate = [IO.Path]::GetFullPath($ProductionData)
  production_userdata_before = $ProductionBefore
  production_userdata_after = $ProductionAfter
  existing_installation_before = $InstallationBefore
  existing_installation_after = $InstallationAfter
  application_payload_before = $ApplicationBefore
  application_payload_after = $ApplicationAfter
  production_userdata_unchanged = $true
  existing_installation_unchanged = $true
  application_payload_unchanged = $true
  internal_userdata_absent = $true
  supported_launchers_force_owner_test_data = $true
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'isolation-proof.json') -Encoding UTF8

# Return the shipped owner data to a clean first-run state, bounded to the delivery.
$OwnerFull = [IO.Path]::GetFullPath($OwnerRoot).TrimEnd('\')
if (-not $OwnerFull.StartsWith($DeliveryRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Refusing cleanup outside delivery root." }
if (Test-Path -LiteralPath $OwnerFull) { Remove-Item -LiteralPath $OwnerFull -Recurse -Force }
New-Item -ItemType Directory -Path $OwnerFull | Out-Null

Remove-Item -LiteralPath $Sandbox -Recurse -Force
Write-Host 'WIN1-P1 OWNER-TEST ISOLATION PASS'
