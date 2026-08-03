[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$Source,
  [Parameter(Mandatory=$true)][string]$SitePackages,
  [Parameter(Mandatory=$true)][string]$Receipt
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Source = [IO.Path]::GetFullPath($Source)
$SitePackages = [IO.Path]::GetFullPath($SitePackages)
$Receipt = [IO.Path]::GetFullPath($Receipt)
$Target = Join-Path $SitePackages 'win1_pytest_windows_baseline.py'
$Deadline = [DateTimeOffset]::UtcNow.AddMinutes(20)

while (-not (Test-Path -LiteralPath $SitePackages -PathType Container)) {
  if ([DateTimeOffset]::UtcNow -ge $Deadline) { throw "Timed out waiting for build venv: $SitePackages" }
  Start-Sleep -Milliseconds 100
}

$Expected = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
Copy-Item -LiteralPath $Source -Destination $Target -Force
$Actual = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Actual -ne $Expected) { throw "Staged pytest baseline plugin hash mismatch: $Target" }

[ordered]@{
  schema='Tianxia.WIN1P1.PytestBaselinePluginStaging.v1'
  status='PASS'
  module='win1_pytest_windows_baseline'
  sha256=$Actual
  temporary_build_venv_only=$true
  app_source_modified=$false
  packaged_runtime_modified=$false
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Receipt -Encoding UTF8
