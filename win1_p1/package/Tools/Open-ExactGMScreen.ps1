[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$DeliveryRoot)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$DeliveryRoot = [IO.Path]::GetFullPath($DeliveryRoot).TrimEnd('\')
$Archive = Join-Path $DeliveryRoot "Exact Bundled GM Screen\HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip"
$Expected = "c281c80e96c718a2c629b65c762b1c053a82eff7201d018a6acca1110c1c0f8f"
$Target = Join-Path $DeliveryRoot "OwnerTestData\ExactGMScreen"

if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
  throw "The exact bundled GM Screen archive is missing. Keep the complete owner-test folder together."
}
$Actual = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Actual -ne $Expected) {
  throw "The exact bundled GM Screen failed its integrity check. Expected $Expected; got $Actual."
}
$TargetFull = [IO.Path]::GetFullPath($Target).TrimEnd('\')
$OwnerRoot = [IO.Path]::GetFullPath((Join-Path $DeliveryRoot "OwnerTestData")).TrimEnd('\')
if (-not $TargetFull.StartsWith($OwnerRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
  throw "The GM Screen target escaped OwnerTestData; stopping safely."
}
if (-not (Test-Path -LiteralPath $TargetFull -PathType Container)) {
  New-Item -ItemType Directory -Path $TargetFull | Out-Null
  Expand-Archive -LiteralPath $Archive -DestinationPath $TargetFull
}
$Launcher = Join-Path $TargetFull "Open_Dao_Dashboard.bat"
if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) {
  throw "The verified GM Screen did not contain Open_Dao_Dashboard.bat."
}
Start-Process -FilePath $Launcher -WorkingDirectory $TargetFull
Write-Host "Opened the exact bundled GM Screen from OwnerTestData."
