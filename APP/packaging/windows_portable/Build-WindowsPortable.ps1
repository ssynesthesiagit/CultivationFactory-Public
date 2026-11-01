[CmdletBinding()]
param(
  [string]$OutputRoot = "",
  [string]$PythonExe = "",
  [string]$NodeExe = "",
  [string]$TempRoot = "",
  [string]$PytestTempRoot = "",
  [string]$PythonCacheRoot = "",
  [switch]$SkipInteractiveAcceptance
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Sha256([string]$Path) {
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Sha256-Text([string]$Text) {
  $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
  $sha = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }
  finally { $sha.Dispose() }
}
function Assert-Hash([string]$Path, [string]$Expected, [string]$Label) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label missing: $Path" }
  $actual = Sha256 $Path
  if ($actual -ne $Expected) { throw "$Label SHA-256 mismatch. Expected $Expected, got $actual" }
}
function Write-Sidecar([string]$Path) {
  $name = [IO.Path]::GetFileName($Path)
  $line = "$(Sha256 $Path)  $name`n"
  [IO.File]::WriteAllText("$Path.sha256", $line, [Text.UTF8Encoding]::new($false))
}
function New-SafeZip([string]$SourcePath, [string]$DestinationPath) {
  Add-Type -AssemblyName System.IO.Compression
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $sourceFull = [IO.Path]::GetFullPath($SourcePath).TrimEnd('\')
  $parentFull = [IO.Directory]::GetParent($sourceFull).FullName.TrimEnd('\')
  if (Test-Path -LiteralPath $DestinationPath) { Remove-Item -LiteralPath $DestinationPath -Force }
  $fileStream = [IO.File]::Open($DestinationPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
  $archive = [IO.Compression.ZipArchive]::new($fileStream, [IO.Compression.ZipArchiveMode]::Create, $false)
  try {
    foreach ($directory in @(Get-Item -LiteralPath $sourceFull) + @(Get-ChildItem -LiteralPath $sourceFull -Recurse -Directory -Force | Sort-Object FullName)) {
      $entryName = $directory.FullName.Substring($parentFull.Length + 1).Replace('\','/') + '/'
      $archive.CreateEntry($entryName) | Out-Null
    }
    foreach ($file in Get-ChildItem -LiteralPath $sourceFull -Recurse -File -Force | Sort-Object FullName) {
      $entryName = $file.FullName.Substring($parentFull.Length + 1).Replace('\','/')
      [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $entryName, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
  } finally {
    $archive.Dispose()
    $fileStream.Dispose()
  }
}
function Find-Python312 {
  $candidates = @(
    @{Exe="py"; Args=@("-3.12")},
    @{Exe="python"; Args=@()}
  )
  foreach ($c in $candidates) {
    try {
      $v = & $c.Exe @($c.Args) -c "import struct,sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor)+'|'+str(struct.calcsize('P')*8))" 2>$null
      if ($LASTEXITCODE -eq 0 -and $v.Trim() -eq "3.12|64") { return $c }
    } catch {}
  }
  throw "Python 3.12 x64 is required on the Windows build machine. Install it from python.org, then rerun this script."
}
function Find-VerifiedNode {
  param([string]$Requested = "")
  $Expected = "63c259c81e5d472b5f11c8d506070130cb04a1ecf84b80377a34ed6ec9048088"
  $Candidates = @()
  if ($Requested) { $Candidates += [IO.Path]::GetFullPath($Requested) }
  try {
    $Command = Get-Command node -CommandType Application -ErrorAction Stop
    $Candidates += $Command.Source
  } catch {}
  if ($env:USERPROFILE) {
    $Candidates += Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
  }
  foreach ($Candidate in @($Candidates | Select-Object -Unique)) {
    if ((Test-Path -LiteralPath $Candidate -PathType Leaf) -and (Sha256 $Candidate) -eq $Expected) {
      return [IO.Path]::GetFullPath($Candidate)
    }
  }
  throw "Verified Node.js runtime not found. Supply -NodeExe with SHA-256 $Expected."
}
function Get-SourceInventory([string]$Root) {
  $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
  return @(Get-ChildItem -LiteralPath $rootFull -Recurse -File | Where-Object {
    $_.FullName -notmatch '[\\/](?:__pycache__|\.pytest_cache)[\\/]' -and $_.Extension -notin @('.pyc', '.pyo')
  } | Sort-Object FullName | ForEach-Object {
    [PSCustomObject]@{
      path = $_.FullName.Substring($rootFull.Length + 1).Replace('\','/')
      size = $_.Length
      sha256 = Sha256 $_.FullName
    }
  })
}

if ($env:OS -ne "Windows_NT" -or -not [Environment]::Is64BitOperatingSystem) {
  throw "This build must execute on native Windows 10/11 x64."
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$ExecutionRoot = (Resolve-Path (Join-Path $SourceRoot "..")).Path
$Inputs = Join-Path $ExecutionRoot "Inputs"
$Factory = Join-Path $Inputs "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
$Foundation = Join-Path $Inputs "Tianxia_Foundation_FactoryApp_Handoff_v1_0.zip"
$Wheelhouse = Join-Path $Inputs "PrivateRuntimeWheels"
Assert-Hash $Factory "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385" "Factory input"
Assert-Hash $Foundation "df80217c64c0808190c85531095e5e78aa96ff6808be369915f36fbb4189771c" "Foundation handoff"
if (-not (Test-Path -LiteralPath $Wheelhouse -PathType Container)) { throw "Private runtime wheelhouse is missing: $Wheelhouse" }

$env:TIANXIA_TEST_FACTORY_ZIP = $Factory
$env:TIANXIA_FOUNDATION_HANDOFF = $Foundation
$env:TIANXIA_TEST_INTEGRITY_SEED = "windows-desktop-window-packaging-focused"

if ($PythonExe) {
  $PythonExe = [IO.Path]::GetFullPath($PythonExe)
  if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "Requested Python executable is missing: $PythonExe" }
  $PythonIdentity = & $PythonExe -c "import struct,sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor)+'|'+str(struct.calcsize('P')*8))"
  if ($LASTEXITCODE -ne 0 -or $PythonIdentity.Trim() -ne "3.12|64") { throw "The requested Python executable must be Python 3.12 x64." }
  $Py = @{Exe=$PythonExe; Args=@()}
} else {
  $Py = Find-Python312
}
if (-not $OutputRoot) { $OutputRoot = Join-Path $ExecutionRoot "WindowsBuildOutput" }
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
$NodeExe = Find-VerifiedNode $NodeExe
$NodeDirectory = Split-Path -Parent $NodeExe
$BuildRoot = Join-Path $ExecutionRoot ".windows_build"
$ProcessStateRoot = Join-Path $ExecutionRoot ".windows_process_state"
if (-not $TempRoot) { $TempRoot = Join-Path $ProcessStateRoot "temp" }
if (-not $PytestTempRoot) { $PytestTempRoot = Join-Path $ProcessStateRoot "pytest" }
if (-not $PythonCacheRoot) { $PythonCacheRoot = Join-Path $ProcessStateRoot "python-cache" }
$TempRoot = [IO.Path]::GetFullPath($TempRoot)
$PytestTempRoot = [IO.Path]::GetFullPath($PytestTempRoot)
$PythonCacheRoot = [IO.Path]::GetFullPath($PythonCacheRoot)
$Venv = Join-Path $BuildRoot "venv"
$Work = Join-Path $BuildRoot "pyinstaller-work"
$Dist = Join-Path $BuildRoot "dist"
$Download = Join-Path $BuildRoot "downloads"
$Evidence = Join-Path $BuildRoot "evidence"
Remove-Item -Recurse -Force $BuildRoot -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $OutputRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $BuildRoot,$Download,$Evidence,$OutputRoot,$TempRoot,$PytestTempRoot,$PythonCacheRoot | Out-Null

# These changes apply only to this PowerShell process and its children.
$env:PATH = "$NodeDirectory;$env:PATH"
$env:TEMP = $TempRoot
$env:TMP = $TempRoot
$env:PYTHONPYCACHEPREFIX = $PythonCacheRoot
$env:PYTHONDONTWRITEBYTECODE = "1"

$SourceInventory = @(Get-SourceInventory $SourceRoot)
$SourceInventory | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Evidence "source-file-inventory.json") -Encoding UTF8
$SourceLines = @($SourceInventory | ForEach-Object { "$($_.path)|$($_.size)|$($_.sha256)" })
$SourceFingerprint = Sha256-Text (($SourceLines -join "`n") + "`n")
[ordered]@{
  algorithm = "sha256(path|size|sha256 lines, UTF-8, LF, sorted by path)"
  file_count = $SourceInventory.Count
  source_fingerprint = $SourceFingerprint
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Evidence "source-fingerprint.json") -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $ScriptDir "DESKTOP_WINDOW_SOURCE_CHANGE_LIST.md") -Destination (Join-Path $Evidence "source-change-list.md")

& $Py.Exe @($Py.Args) -m venv $Venv
$Vpy = Join-Path $Venv "Scripts\python.exe"
& $Vpy -m pip install --upgrade "pip==25.1.1"
if ($LASTEXITCODE -ne 0) { throw "Pinned pip installation failed." }
& $Vpy -m pip install -r (Join-Path $ScriptDir "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "Pinned build dependency installation failed." }
& $Vpy (Join-Path $ScriptDir "windows_build_selfcheck.py") --source-root $SourceRoot --factory $Factory --foundation $Foundation | Tee-Object -FilePath (Join-Path $Evidence "prebuild-selfcheck.json")
if ($LASTEXITCODE -ne 0) { throw "Prebuild self-check failed." }

$PythonSyntaxLog = Join-Path $Evidence "python-compilation.log"
& $Vpy -m compileall -q -f $SourceRoot 2>&1 | Tee-Object -FilePath $PythonSyntaxLog
if ($LASTEXITCODE -ne 0) { throw "Focused Python compilation gate failed." }
$JavaScriptFiles = @(Get-ChildItem -LiteralPath $SourceRoot -Recurse -File | Where-Object {
  $_.Extension -in @(".js", ".mjs") -and
  $_.FullName -notmatch '[\\/](?:node_modules|\.windows_build)[\\/]'
} | Sort-Object FullName)
$JavaScriptSyntaxLog = Join-Path $Evidence "javascript-syntax.log"
[IO.File]::WriteAllText($JavaScriptSyntaxLog, "", [Text.UTF8Encoding]::new($false))
foreach ($JavaScriptFile in $JavaScriptFiles) {
  & $NodeExe --check $JavaScriptFile.FullName 2>&1 | Tee-Object -FilePath $JavaScriptSyntaxLog -Append
  if ($LASTEXITCODE -ne 0) { throw "JavaScript syntax gate failed: $($JavaScriptFile.FullName)" }
}
[ordered]@{
  status = "PASS"
  python_source_root_compiled = $true
  javascript_file_count = $JavaScriptFiles.Count
  javascript_files = @($JavaScriptFiles | ForEach-Object { $_.FullName.Substring($SourceRoot.Length + 1).Replace('\','/') })
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Evidence "syntax-gates.json") -Encoding UTF8

# Focused source tests only; never the unrelated full suite. Gate 5.1 nodes run
# in fresh pytest processes because the exact live-seed fixture is intentionally
# large and must not inherit memory from the in-process API fixture.
$FocusedTestNodes = @(
  "tests/test_cg1_character_creation_modes.py",
  "tests/test_w5_p1r_primary_character_creation.py",
  "tests/test_w5_p1r_r1_production_endpoints.py",
  "tests/test_w5_p1r_r2_owner_surface.py",
  "tests/test_w5_production_receipt_identity.py",
  "tests/test_w1_owner_workflow.py",
  "tests/test_m1_c3ar_w1_bounded_merge.py",
  "tests/test_c3a_fire_qi_combat_sheet.py",
  "tests/test_c3ar_runtime_executability.py",
  "tests/test_c3b_pre_encounter.py",
  "tests/test_c3d_p1_portable_live_combat.py",
  "tests/test_c3d_p1r_historical_compatibility.py",
  "tests/test_r6_6_3_launcher_state_race.py",
  "tests/test_r6_6_5_sphere_talent_authority.py",
  "tests/test_r6_6_6_catalog_data_packaging.py",
  "tests/test_r6_6_7_character_builder_intake_catalog.py",
  "tests/test_r6_6_7_1_character_builder_owner_feedback.py",
  "tests/test_character_sheet_builder.py",
  "tests/test_sphere_talent_ui.py",
  "tests/test_c2c1_command6_portable_character.py",
  "tests/test_r66_native_windows_corrections.py",
  "tests/test_combat_battle_history.py",
  "tests/test_combat_gate5_integration.py",
  "tests/test_windows_portable_packaging.py",
  "tests/test_vendor_adapter.py",
  "tests/test_combat_gate5_1_correction.py::test_command_cui_candidates_are_mode_specific_and_deterministic",
  "tests/test_combat_gate5_1_correction.py::test_engine_rejects_malformed_allied_cui_strike_without_mutation",
  "tests/test_combat_gate5_1_correction.py::test_controller_never_scores_allied_strike_and_selects_hostile_strike",
  "tests/test_combat_gate5_1_correction.py::test_controller_uses_cui_dodge_when_no_useful_strike_or_dash_exists",
  "tests/test_combat_gate5_1_correction.py::test_controller_prefers_end_turn_and_suppresses_repeated_hold",
  "tests/test_combat_gate5_1_correction.py::test_api_ai_frame_and_ui_use_corrected_candidate_authority",
  "tests/test_combat_gate5_1_correction.py::test_exact_live_seed_has_only_active_hostile_cui_strikes_and_replays"
)
$FocusedTestLog = Join-Path $Evidence "focused-tests.log"
[IO.File]::WriteAllText($FocusedTestLog, "", [Text.UTF8Encoding]::new($false))
Push-Location $SourceRoot
try {
  for ($Index = 0; $Index -lt $FocusedTestNodes.Count; $Index++) {
    $Node = $FocusedTestNodes[$Index]
    "=== $Node ===" | Tee-Object -FilePath $FocusedTestLog -Append
    $XmlPath = Join-Path $Evidence ("focused-tests-{0:d2}.xml" -f ($Index + 1))
    $NodeTemp = Join-Path $PytestTempRoot ("node-{0:d2}" -f ($Index + 1))
    & $Vpy -m pytest -q $Node -p no:cacheprovider --basetemp $NodeTemp --junitxml $XmlPath 2>&1 | Tee-Object -FilePath $FocusedTestLog -Append
    if ($LASTEXITCODE -ne 0) { throw "Focused desktop-window packaging test failed: $Node" }
  }
  $FocusedTestNodes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Evidence "focused-test-nodes.json") -Encoding UTF8
} finally { Pop-Location }

$EmbedUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
$EmbedSha = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
$EmbedZip = Join-Path $Download "python-3.12.10-embed-amd64.zip"
Invoke-WebRequest -Uri $EmbedUrl -OutFile $EmbedZip
Assert-Hash $EmbedZip $EmbedSha "CPython embeddable runtime"
$PrivatePython = Join-Path $BuildRoot "PrivatePython"
Expand-Archive -LiteralPath $EmbedZip -DestinationPath $PrivatePython
$Pth = Join-Path $PrivatePython "python312._pth"
@("python312.zip", ".", "Lib\site-packages", "import site") | Set-Content -LiteralPath $Pth -Encoding ASCII
New-Item -ItemType Directory -Force (Join-Path $PrivatePython "Lib\site-packages") | Out-Null
& $Vpy -m pip install --no-index --find-links $Wheelhouse --target (Join-Path $PrivatePython "Lib\site-packages") -r (Join-Path $ScriptDir "requirements-private-runtime.txt")
if ($LASTEXITCODE -ne 0) { throw "Private helper runtime installation failed." }
Copy-Item -LiteralPath (Join-Path $PrivatePython "python.exe") -Destination (Join-Path $PrivatePython "python3.exe") -Force

$SavedErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Vpy -m PyInstaller --clean --noconfirm --workpath $Work --distpath $Dist (Join-Path $ScriptDir "TianxiaFactory.spec") 2>&1 | Tee-Object -FilePath (Join-Path $Evidence "pyinstaller-build.log")
$PyInstallerExitCode = $LASTEXITCODE
$ErrorActionPreference = $SavedErrorActionPreference
if ($PyInstallerExitCode -ne 0) { throw "PyInstaller desktop-window build failed." }

$Portable = Join-Path $OutputRoot "Tianxia Factory"
Copy-Item -Recurse -Force (Join-Path $Dist "Tianxia Factory") $Portable
Copy-Item -Recurse -Force $PrivatePython (Join-Path $Portable "Runtime\PrivatePython")
New-Item -ItemType Directory -Force (Join-Path $Portable "BundledContent") | Out-Null
$UserData = Join-Path $Portable "UserData"
$UserDataDirectories = @("Database", "Inbox", "Exports", "InstalledContent", "Vendor", "Logs", "Backups", "security", "secrets", "WebView2")
foreach ($relative in $UserDataDirectories) { New-Item -ItemType Directory -Force (Join-Path $UserData $relative) | Out-Null }
Copy-Item -LiteralPath $Factory -Destination (Join-Path $Portable "BundledContent")
Copy-Item -LiteralPath $Foundation -Destination (Join-Path $Portable "BundledContent")
New-Item -ItemType Directory -Force (Join-Path $Portable "Runtime\BundledContent") | Out-Null
Copy-Item -LiteralPath $Factory -Destination (Join-Path $Portable "Runtime\BundledContent")
Copy-Item -LiteralPath (Join-Path $ScriptDir "README_FIRST_RUN.txt") -Destination (Join-Path $Portable "README_FIRST_RUN.txt")
Copy-Item -LiteralPath (Join-Path $ScriptDir "VERSION.json") -Destination (Join-Path $Portable "VERSION.json")
Copy-Item -LiteralPath (Join-Path $ScriptDir "START_TIANXIA_CURRENT_OWNER_TEST.cmd") -Destination (Join-Path $Portable "START_TIANXIA_CURRENT_OWNER_TEST.cmd")
Copy-Item -LiteralPath (Join-Path $ScriptDir "SAFE_REMOVAL.txt") -Destination (Join-Path $Portable "SAFE_REMOVAL.txt")
Copy-Item -LiteralPath (Join-Path $SourceRoot "OWNER_TEST_CHECKLIST.md") -Destination (Join-Path $Portable "OWNER_TEST_CHECKLIST.md")
$OwnerFixtures = Join-Path $SourceRoot "W5_P1_ACCEPTANCE\owner_test_fixtures"
if (-not (Test-Path -LiteralPath $OwnerFixtures -PathType Container)) {
  throw "Sealed W5 owner-test fixtures are missing: $OwnerFixtures"
}
Copy-Item -LiteralPath $OwnerFixtures -Destination (Join-Path $Portable "OwnerTestFixtures") -Recurse -Force

# Exact character-authority runtime-data boundary assertions.
$CatalogAuthoritySource = Join-Path $SourceRoot "catalog_authority\cat3\generated\catalog_authority.v1.json"
$CatalogAuthorityRuntime = Join-Path $Portable "Runtime\catalog_authority\cat3\generated\catalog_authority.v1.json"
$SphereTalentUiSource = Join-Path $SourceRoot "static\sphere_talent_logic.js"
$SphereTalentUiRuntime = Join-Path $Portable "Runtime\static\sphere_talent_logic.js"
$GmScreenSource = Join-Path $SourceRoot "gm_screen\HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip"
$GmScreenRuntime = Join-Path $Portable "Runtime\gm_screen\HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip"
Assert-Hash $CatalogAuthorityRuntime (Sha256 $CatalogAuthoritySource) "Packaged catalog authority"
Assert-Hash $SphereTalentUiRuntime (Sha256 $SphereTalentUiSource) "Packaged Sphere/Talent UI logic"
Assert-Hash $GmScreenRuntime (Sha256 $GmScreenSource) "Packaged GM Screen authority"
[ordered]@{
  status = "PASS"
  mappings = @(
    [ordered]@{ source = "catalog_authority/cat3/generated/catalog_authority.v1.json"; runtime = "Runtime/catalog_authority/cat3/generated/catalog_authority.v1.json"; sha256 = Sha256 $CatalogAuthorityRuntime },
    [ordered]@{ source = "static/sphere_talent_logic.js"; runtime = "Runtime/static/sphere_talent_logic.js"; sha256 = Sha256 $SphereTalentUiRuntime },
    [ordered]@{ source = "gm_screen/HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip"; runtime = "Runtime/gm_screen/HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip"; sha256 = Sha256 $GmScreenRuntime }
  )
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Evidence "runtime-data-packaging-assertions.json") -Encoding UTF8

# Remove development residue copied through source/data collection.
$PortableFull = [IO.Path]::GetFullPath($Portable).TrimEnd('\')
$ForbiddenDirectories = Get-ChildItem -LiteralPath $PortableFull -Recurse -Directory | Where-Object {
  $_.Name -in @("tests", "reports", "__pycache__", ".pytest_cache")
} | Sort-Object { $_.FullName.Length } -Descending
foreach ($Directory in $ForbiddenDirectories) {
  $Candidate = [IO.Path]::GetFullPath($Directory.FullName)
  if (-not $Candidate.StartsWith($PortableFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing cleanup outside the portable root: $Candidate"
  }
  Remove-Item -LiteralPath $Candidate -Recurse -Force
}
Get-ChildItem -LiteralPath $PortableFull -Recurse -File | Where-Object { $_.Extension -in @(".pyc", ".pyo") } | Remove-Item -Force

& $Vpy (Join-Path $ScriptDir "windows_build_selfcheck.py") --source-root $SourceRoot --factory $Factory --foundation $Foundation --portable-root $Portable | Tee-Object -FilePath (Join-Path $Evidence "postbuild-selfcheck.json")
if ($LASTEXITCODE -ne 0) { throw "Postbuild self-check failed." }

$NativeAcceptancePassed = $false
if (-not $SkipInteractiveAcceptance) {
  & (Join-Path $ScriptDir "Verify-WindowsPortable.ps1") -PortableRoot $Portable -EvidenceRoot $Evidence
  if ($LASTEXITCODE -ne 0) { throw "Windows desktop-window acceptance failed." }
  $AcceptanceRecord = Get-Content -LiteralPath (Join-Path $Evidence "windows-desktop-window-acceptance.json") -Raw | ConvertFrom-Json
  if ($AcceptanceRecord.status -ne "PASS") { throw "Windows desktop-window acceptance record did not say PASS." }
  $NativeAcceptancePassed = $true
} else {
  [ordered]@{
    status = "NOT_RUN"
    reason = "Build invoked with -SkipInteractiveAcceptance"
    owner_test_status = "NOT_READY"
  } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Evidence "native-acceptance-not-run.json") -Encoding UTF8
}

# Acceptance mutates UserData. Preserve evidence, then return the owner package to a clean first-run state.
$UserDataFull = [IO.Path]::GetFullPath($UserData).TrimEnd('\')
if (-not $UserDataFull.StartsWith($PortableFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
  throw "Refusing UserData cleanup outside the portable root: $UserDataFull"
}
foreach ($Item in Get-ChildItem -LiteralPath $UserDataFull -Force) {
  $Candidate = [IO.Path]::GetFullPath($Item.FullName)
  if (-not $Candidate.StartsWith($UserDataFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing cleanup outside UserData: $Candidate"
  }
  Remove-Item -LiteralPath $Candidate -Recurse -Force
}
foreach ($relative in $UserDataDirectories) { New-Item -ItemType Directory -Force (Join-Path $UserDataFull $relative) | Out-Null }
$GeneratedFiles = @(Get-ChildItem -LiteralPath $UserDataFull -Recurse -File -Force)
if ($GeneratedFiles.Count -ne 0) { throw "Generated UserData files remained in the owner distribution." }
$CleanDirs = @(Get-ChildItem -LiteralPath $UserDataFull -Recurse -Directory -Force | ForEach-Object { $_.FullName.Substring($UserDataFull.Length + 1).Replace('\','/') } | Sort-Object)
[ordered]@{
  status = "PASS"
  file_count = 0
  empty_directories = $CleanDirs
  forbidden_generated_data_present = $false
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Evidence "clean-userdata-proof.json") -Encoding UTF8

# Bind the packaged VERSION record to this exact build and acceptance result.
$VersionPath = Join-Path $Portable "VERSION.json"
$Version = Get-Content -LiteralPath $VersionPath -Raw | ConvertFrom-Json
$Version.build_status = $(if ($NativeAcceptancePassed) { "READY_FOR_OWNER_TESTING" } else { "BUILD_ONLY_NATIVE_ACCEPTANCE_NOT_RUN" })
$Version.windows_acceptance = $NativeAcceptancePassed
$Version.native_windows_acceptance_status = $(if ($NativeAcceptancePassed) { "PASS" } else { "NOT_RUN" })
$Version.owner_test_status = $(if ($NativeAcceptancePassed) { "W5_P1R_R3_NATIVE_WINDOWS_OWNER_TEST_BUILD_READY" } else { "NOT_READY" })
$Version | Add-Member -NotePropertyName status -NotePropertyValue $(
  if ($NativeAcceptancePassed) { "W5_P1R_R3_NATIVE_WINDOWS_OWNER_TEST_BUILD_READY" } else { "W5_P1R_R3_NATIVE_ACCEPTANCE_NOT_RUN" }
) -Force
$Version | Add-Member -NotePropertyName source_disposition -NotePropertyValue "W5_P1R_R3_NATIVE_BUILD_GATE_ALIGNED" -Force
$Version | Add-Member -NotePropertyName source_parent_sha256 -NotePropertyValue "0ecc7684b477be69fe2b6d3605de2b0b7c91ea0ae8202c5cb8f0baafcf97a2c5" -Force
$Version | Add-Member -NotePropertyName final_release_readiness_claimed -NotePropertyValue $false -Force
$Version | Add-Member -NotePropertyName built_source_fingerprint -NotePropertyValue $SourceFingerprint -Force
$Version | Add-Member -NotePropertyName built_at_utc -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
$Version | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $VersionPath -Encoding UTF8

& $Vpy (Join-Path $ScriptDir "windows_build_selfcheck.py") --source-root $SourceRoot --factory $Factory --foundation $Foundation --portable-root $Portable | Tee-Object -FilePath (Join-Path $Evidence "postclean-selfcheck.json")
if ($LASTEXITCODE -ne 0) { throw "Post-clean distribution self-check failed." }

$PortableChecksumPath = Join-Path $Portable "SHA256SUMS.txt"
$PortableChecksumLines = @(Get-ChildItem -LiteralPath $Portable -Recurse -File | Where-Object {
  $_.FullName -ne $PortableChecksumPath
} | Sort-Object FullName | ForEach-Object {
  "$(Sha256 $_.FullName)  $($_.FullName.Substring($Portable.Length + 1).Replace('\','/'))"
})
[IO.File]::WriteAllText(
  $PortableChecksumPath,
  (($PortableChecksumLines -join "`n") + "`n"),
  [Text.UTF8Encoding]::new($false)
)

$Inventory = Get-ChildItem -LiteralPath $Portable -Recurse -File | Sort-Object FullName | ForEach-Object {
  [PSCustomObject]@{ path=$_.FullName.Substring($Portable.Length+1).Replace('\','/'); size=$_.Length; sha256=Sha256 $_.FullName }
}
$Inventory | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Evidence "portable-file-inventory.json") -Encoding UTF8
$BuildEnv = [ordered]@{
  os = [Environment]::OSVersion.VersionString
  powershell = $PSVersionTable.PSVersion.ToString()
  python = (& $Vpy --version)
  node = (& $NodeExe --version)
  node_exe = $NodeExe
  node_sha256 = Sha256 $NodeExe
  temp_root = $TempRoot
  pytest_temp_root = $PytestTempRoot
  python_cache_root = $PythonCacheRoot
  source_root = $SourceRoot
  source_fingerprint = $SourceFingerprint
  factory_sha256 = Sha256 $Factory
  foundation_sha256 = Sha256 $Foundation
  native_acceptance_passed = $NativeAcceptancePassed
  built_at_utc = [DateTime]::UtcNow.ToString('o')
}
$BuildEnv | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Evidence "build-environment.json") -Encoding UTF8

$PostSourceInventory = @(Get-SourceInventory $SourceRoot)
$PostSourceLines = @($PostSourceInventory | ForEach-Object { "$($_.path)|$($_.size)|$($_.sha256)" })
$PostSourceFingerprint = Sha256-Text (($PostSourceLines -join "`n") + "`n")
[ordered]@{
  status = if ($PostSourceFingerprint -eq $SourceFingerprint) { "PASS" } else { "FAIL" }
  before_source_fingerprint = $SourceFingerprint
  after_source_fingerprint = $PostSourceFingerprint
  unchanged = $PostSourceFingerprint -eq $SourceFingerprint
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Evidence "source-fingerprint-before-after.json") -Encoding UTF8
if ($PostSourceFingerprint -ne $SourceFingerprint) {
  throw "The source tree changed during the native Windows build."
}

# Historical merge-gate identity retained for audit discoverability only:
# Tianxia_W5_P1_Current_Windows_Portable.zip
# Tianxia_W5_P1_Native_Windows_Evidence.zip
$PortableZip = Join-Path $OutputRoot "Tianxia_W5_P1R_R3_Owner_Test_Portable.zip"
New-SafeZip $Portable $PortableZip
Write-Sidecar $PortableZip

$EvidencePackage = Join-Path $OutputRoot "Tianxia Factory W5-P1R-R3 Native Windows Evidence"
New-Item -ItemType Directory -Force $EvidencePackage | Out-Null
Copy-Item -Recurse -Force (Join-Path $Evidence "*") $EvidencePackage
Copy-Item -LiteralPath $VersionPath -Destination (Join-Path $EvidencePackage "VERSION.json")
$EvidenceZip = Join-Path $OutputRoot "Tianxia_W5_P1R_R3_Native_Windows_Evidence.zip"
New-SafeZip $EvidencePackage $EvidenceZip
Write-Sidecar $EvidenceZip

if ((Get-Item $PortableZip).Length -gt 209715200 -or (Get-Item $EvidenceZip).Length -gt 209715200) {
  throw "A returned attachment exceeds 200 MB."
}
Write-Host "W5-P1R-R3 NATIVE OWNER-TEST BUILD COMPLETE"
Write-Host "Native acceptance passed: $NativeAcceptancePassed"
Write-Host $PortableZip
Write-Host $EvidenceZip
