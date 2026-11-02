[CmdletBinding()]
param(
  [string]$OutputRoot = "",
  [string]$PythonExe = "",
  [switch]$SkipInteractiveAcceptance,
  [switch]$VerifyOnly
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Find-Python312 {
  foreach ($Candidate in @(@{Exe="py";Args=@("-3.12")}, @{Exe="python";Args=@()})) {
    try {
      $Identity = & $Candidate.Exe @($Candidate.Args) -c "import struct,sys; print(f'{sys.version_info.major}.{sys.version_info.minor}|{struct.calcsize('P')*8}')" 2>$null
      if ($LASTEXITCODE -eq 0 -and $Identity.Trim() -eq "3.12|64") { return $Candidate }
    } catch {}
  }
  throw "Python 3.12 x64 is required."
}

if ($env:OS -ne "Windows_NT" -or -not [Environment]::Is64BitOperatingSystem) {
  throw "This M1 build must execute on native Windows 10/11 x64."
}
$SourceRoot = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..\.."))
$ExecutionRoot = Split-Path -Parent $SourceRoot
$BuildScript = Join-Path $SourceRoot "packaging\windows_portable\Build-WindowsPortable.ps1"
$Preflight = Join-Path $SourceRoot "packaging\windows_portable\w1_source_preflight.py"
if (-not (Test-Path -LiteralPath $BuildScript -PathType Leaf) -or -not (Test-Path -LiteralPath $Preflight -PathType Leaf)) {
  throw "M1 Windows build/preflight script is missing."
}
if ($PythonExe) {
  $Py = @{Exe=[IO.Path]::GetFullPath($PythonExe);Args=@()}
} else { $Py = Find-Python312 }

# Tool-owned evidence must remain outside the sealed source root.
$VerificationReportRoot = Join-Path ([IO.Path]::GetTempPath()) "Tianxia_Factory_M1_Input_Verification"
$Root = $SourceRoot
$RootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
$VerificationReportRoot = [IO.Path]::GetFullPath($VerificationReportRoot).TrimEnd('\')
if ($VerificationReportRoot.Equals($RootFull, [StringComparison]::OrdinalIgnoreCase) -or
    $VerificationReportRoot.StartsWith($RootFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
  throw "Verification report path resolves inside the sealed package root"
}
New-Item -ItemType Directory -Force $VerificationReportRoot | Out-Null
$VerificationReport = Join-Path $VerificationReportRoot "NativeBuildInputVerification.json"
& $Py.Exe @($Py.Args) $Preflight --source-root $SourceRoot --execution-root $ExecutionRoot --report $VerificationReport
if ($LASTEXITCODE -ne 0) { throw "M1 native-build preflight failed. See $VerificationReport" }
Write-Host "M1 sealed source, exact external inputs, and wheelhouse verified."
Write-Host "Verification report: $VerificationReport"
if ($VerifyOnly) { exit 0 }

$Params = @{}
if ($OutputRoot) { $Params.OutputRoot = $OutputRoot }
if ($PythonExe) { $Params.PythonExe = $PythonExe }
if ($SkipInteractiveAcceptance) { $Params.SkipInteractiveAcceptance = $true }
& $BuildScript @Params
if ($LASTEXITCODE -ne 0) { throw "M1 native build failed with exit code $LASTEXITCODE" }
