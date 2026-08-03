[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$SourceRoot,
  [Parameter(Mandatory=$true)][string]$Signal,
  [Parameter(Mandatory=$true)][string]$TargetRoot,
  [Parameter(Mandatory=$true)][string]$Receipt
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
$Signal = [IO.Path]::GetFullPath($Signal)
$TargetRoot = [IO.Path]::GetFullPath($TargetRoot)
$Receipt = [IO.Path]::GetFullPath($Receipt)
$Deadline = [DateTimeOffset]::UtcNow.AddMinutes(115)
$RequiredFiles = @(
  'background_origin_talent_routes.v1.json',
  'canonical_spheres.v1.json'
)

while (-not (Test-Path -LiteralPath $Signal -PathType Leaf)) {
  if ([DateTimeOffset]::UtcNow -ge $Deadline) { throw "Timed out waiting for accepted portable collection: $Signal" }
  Start-Sleep -Milliseconds 100
}

$Records = @($RequiredFiles | ForEach-Object {
  $Name = $_
  $Source = Join-Path $SourceRoot $Name
  $Target = Join-Path $TargetRoot $Name
  $Expected = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
  Copy-Item -LiteralPath $Source -Destination $Target -Force
  $Actual = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($Actual -ne $Expected) { throw "Staged accepted runtime data hash mismatch: $Target" }
  [ordered]@{
    source="APP/catalog_authority/cat1/data/$Name"
    runtime="Runtime/catalog_authority/cat1/data/$Name"
    bytes=(Get-Item -LiteralPath $Target).Length
    sha256=$Actual
  }
})

[ordered]@{
  schema='Tianxia.WIN1P1.AcceptedRuntimeDataStaging.v1'
  status='PASS'
  reason='Accepted PyInstaller spec omits the CAT1 JSON files required by postbuild self-check and native service startup.'
  records=$Records
  app_source_modified=$false
  product_logic_modified=$false
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Receipt -Encoding UTF8
