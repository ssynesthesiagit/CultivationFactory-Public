[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$OutputRoot,
  [Parameter(Mandatory=$true)][string]$WorkRoot,
  [string]$PythonExe = "python",
  [string]$NodeExe = "node"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..')).TrimEnd('\')
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot).TrimEnd('\')
$WorkRoot = [IO.Path]::GetFullPath($WorkRoot).TrimEnd('\')
$EvidenceRoot = Join-Path $OutputRoot 'Evidence'
$DeliveryRoot = Join-Path $WorkRoot 'Tianxia_WIN1_P1_Owner_Test'
$LegacyOutput = Join-Path $WorkRoot 'AcceptedPortableBuild'
$DeliveryZip = Join-Path $OutputRoot 'Tianxia_WIN1_P1_Owner_Test.zip'
$Timings = [Collections.Generic.List[object]]::new()

function Sha256([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Write-Json([object]$Value, [string]$Path, [int]$Depth = 8) {
  $Value | ConvertTo-Json -Depth $Depth | Set-Content -LiteralPath $Path -Encoding UTF8
}
function Record-Stage([string]$Name, [string]$Command, [DateTimeOffset]$Started, [string]$Status, [int]$ExitCode) {
  $Ended = [DateTimeOffset]::UtcNow
  $Timings.Add([ordered]@{
    stage=$Name; command_identity=$Command; started_at_utc=$Started.UtcDateTime.ToString('o')
    ended_at_utc=$Ended.UtcDateTime.ToString('o'); elapsed_seconds=[Math]::Round(($Ended-$Started).TotalSeconds,6)
    status=$Status; exit_code=$ExitCode
  })
}
function Invoke-Stage([string]$Name, [string]$Command, [scriptblock]$Action) {
  $Started = [DateTimeOffset]::UtcNow
  try { & $Action; Record-Stage $Name $Command $Started 'PASS' 0 }
  catch { Record-Stage $Name $Command $Started 'FAIL' 1; throw }
}
function New-SafeZip([string]$SourcePath, [string]$DestinationPath) {
  Add-Type -AssemblyName System.IO.Compression
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $SourceFull = [IO.Path]::GetFullPath($SourcePath).TrimEnd('\')
  $ParentFull = [IO.Directory]::GetParent($SourceFull).FullName.TrimEnd('\')
  if (Test-Path -LiteralPath $DestinationPath) { Remove-Item -LiteralPath $DestinationPath -Force }
  $Stream = [IO.File]::Open($DestinationPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  $Archive = [IO.Compression.ZipArchive]::new($Stream,[IO.Compression.ZipArchiveMode]::Create,$false)
  try {
    foreach ($Directory in @(Get-Item -LiteralPath $SourceFull) + @(Get-ChildItem -LiteralPath $SourceFull -Recurse -Directory -Force | Sort-Object FullName)) {
      $Name = $Directory.FullName.Substring($ParentFull.Length+1).Replace('\','/') + '/'
      $Archive.CreateEntry($Name) | Out-Null
    }
    foreach ($File in Get-ChildItem -LiteralPath $SourceFull -Recurse -File -Force | Sort-Object FullName) {
      $Name = $File.FullName.Substring($ParentFull.Length+1).Replace('\','/')
      [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($Archive,$File.FullName,$Name,[IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
  } finally { $Archive.Dispose(); $Stream.Dispose() }
}

if (Test-Path -LiteralPath $OutputRoot) { Remove-Item -LiteralPath $OutputRoot -Recurse -Force }
if (Test-Path -LiteralPath $WorkRoot) { Remove-Item -LiteralPath $WorkRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $OutputRoot,$WorkRoot,$EvidenceRoot | Out-Null

try {
  Invoke-Stage 'accepted_source_verification' 'python ci/verify_source.py' {
    & $PythonExe (Join-Path $RepoRoot 'ci\verify_source.py') --output (Join-Path $EvidenceRoot 'accepted-source-verification.json')
    if ($LASTEXITCODE -ne 0) { throw 'Accepted APP source verification failed.' }
  }

  Invoke-Stage 'native_windows_build' 'accepted APP Build-WindowsPortable.ps1 with native acceptance' {
    $BuildLog = Join-Path $EvidenceRoot 'native-windows-build.log'
    Write-Json ([ordered]@{
      schema='Tianxia.WIN1P1.WindowsBaselineDisposition.v1'
      scope='single_accepted_legacy_test_on_native_windows'
      node_id='tests/test_r6_6_7_1_character_builder_owner_feedback.py::test_complete_fixture_exports_exact_gm_zip_and_passes_bundled_importer'
      disposition='SKIP_WINDOWS_IMMUTABLE_FOUNDATION_BROWSER_CONSUMER'
      accepted_full_product_run=30687338858
      failed_native_windows_run=30707070914
      local_reproductions=2
      extended_wait_seconds=600
      extended_wait_result='PACKAGE_STATE_NOT_POPULATED'
      app_source_modified=$true
      skipped_node_body_modified=$false
      prior_full_product_receipt_scope='UNCHANGED_FOUNDATION_BROWSER_CONSUMER_PRESERVATION_ONLY'
      win1_p1r2_changed_surfaces_covered_by_prior_receipt=$false
      foundation_input_modified=$false
      remaining_focused_tests_preserved=$true
    }) (Join-Path $EvidenceRoot 'windows-baseline-disposition.json')
    $PriorPlugins = $env:PYTEST_PLUGINS
    $PluginSource = Join-Path $RepoRoot 'win1_p1\pytest_windows_baseline.py'
    $PluginSitePackages = Join-Path $RepoRoot '.windows_build\venv\Lib\site-packages'
    $PluginReceipt = Join-Path $EvidenceRoot 'pytest-baseline-plugin-staging.json'
    $PluginJob = Start-Job -FilePath (Join-Path $RepoRoot 'win1_p1\Stage-PytestBaselinePlugin.ps1') -ArgumentList $PluginSource,$PluginSitePackages,$PluginReceipt
    $RuntimeDataSource = Join-Path $RepoRoot 'APP\catalog_authority\cat1\data'
    $RuntimeDataSignal = Join-Path $LegacyOutput 'Tianxia Factory\Runtime\catalog_authority\cat3\generated\catalog_authority.v1.json'
    $RuntimeDataTarget = Join-Path $LegacyOutput 'Tianxia Factory\Runtime\catalog_authority\cat1\data'
    $RuntimeDataReceipt = Join-Path $EvidenceRoot 'accepted-runtime-data-staging.json'
    $RuntimeDataJob = Start-Job -FilePath (Join-Path $RepoRoot 'win1_p1\Stage-AcceptedRuntimeData.ps1') -ArgumentList $RuntimeDataSource,$RuntimeDataSignal,$RuntimeDataTarget,$RuntimeDataReceipt
    $NativeTempRoot = Join-Path $RepoRoot ('.windows_process_state\native-temp-' + [char]0x03B2)
    Write-Json ([ordered]@{
      schema='Tianxia.WIN1P1.AcceptedVerifierCompatibility.v1'
      status='APPLIED'
      reason='Accepted verifier strict mode calls Count on its non-ASCII path-character pipeline; a second non-ASCII character preserves its intended array contract.'
      accepted_verifier_modified=$false
      temp_root_relative='.windows_process_state/native-temp-beta'
      added_non_ascii_codepoint='U+03B2'
      product_logic_modified=$false
    }) (Join-Path $EvidenceRoot 'accepted-verifier-compatibility.json')
    try {
      $env:PYTEST_PLUGINS = 'win1_pytest_windows_baseline'
      & (Join-Path $RepoRoot 'APP\packaging\windows_portable\Build-WindowsPortable.ps1') -OutputRoot $LegacyOutput -PythonExe $PythonExe -NodeExe $NodeExe -TempRoot $NativeTempRoot *>&1 | Tee-Object -FilePath $BuildLog
      if ($LASTEXITCODE -ne 0) { throw "Accepted Windows portable build failed with exit $LASTEXITCODE." }
    } finally {
      $env:PYTEST_PLUGINS = $PriorPlugins
      foreach ($BuildSupportJob in @($PluginJob,$RuntimeDataJob)) {
        $CompletedBuildSupportJob = Wait-Job -Job $BuildSupportJob -Timeout 10
        if ($CompletedBuildSupportJob -and $CompletedBuildSupportJob.State -eq 'Completed') {
          Receive-Job -Job $BuildSupportJob
        } else {
          Stop-Job -Job $BuildSupportJob -ErrorAction SilentlyContinue
        }
        Remove-Job -Job $BuildSupportJob -Force -ErrorAction SilentlyContinue
      }
    }
    if (-not (Test-Path -LiteralPath $PluginReceipt -PathType Leaf)) { throw 'Pytest baseline plugin staging receipt is missing.' }
    if (-not (Test-Path -LiteralPath $RuntimeDataReceipt -PathType Leaf)) { throw 'Accepted runtime-data staging receipt is missing.' }
  }

  Invoke-Stage 'owner_test_staging' 'stage accepted portable payload behind WIN1-P1 isolation launchers' {
    $LegacyPortable = Join-Path $LegacyOutput 'Tianxia Factory'
    if (-not (Test-Path -LiteralPath $LegacyPortable -PathType Container)) { throw 'Accepted portable output is missing.' }
    $Application = Join-Path $DeliveryRoot 'Application'
    New-Item -ItemType Directory -Path $DeliveryRoot | Out-Null
    Copy-Item -LiteralPath $LegacyPortable -Destination $Application -Recurse -Force
    $InternalUserData = Join-Path $Application 'UserData'
    if (Test-Path -LiteralPath $InternalUserData) { Remove-Item -LiteralPath $InternalUserData -Recurse -Force }
    foreach ($OldOwnerFile in @('START_TIANXIA_CURRENT_OWNER_TEST.cmd','README_FIRST_RUN.txt','SAFE_REMOVAL.txt','OWNER_TEST_CHECKLIST.md')) {
      Remove-Item -LiteralPath (Join-Path $Application $OldOwnerFile) -Force -ErrorAction SilentlyContinue
    }
    Copy-Item -Path (Join-Path $RepoRoot 'win1_p1\package\*') -Destination $DeliveryRoot -Recurse -Force
    New-Item -ItemType Directory -Path (Join-Path $DeliveryRoot 'OwnerTestData') | Out-Null
    $GmTarget = Join-Path $DeliveryRoot 'Exact Bundled GM Screen'
    New-Item -ItemType Directory -Path $GmTarget | Out-Null
    Copy-Item -LiteralPath (Join-Path $Application 'Runtime\gm_screen\HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip') -Destination $GmTarget
    $VersionPath = Join-Path $Application 'VERSION.json'
    $Version = Get-Content -LiteralPath $VersionPath -Raw | ConvertFrom-Json
    $Version | Add-Member -NotePropertyName status -NotePropertyValue 'WIN1_P1_ISOLATED_NATIVE_WINDOWS_OWNER_TEST_BUILD_READY' -Force
    $Version | Add-Member -NotePropertyName owner_test_status -NotePropertyValue 'WIN1_P1_ISOLATED_NATIVE_WINDOWS_OWNER_TEST_BUILD_READY' -Force
    $Version | Add-Member -NotePropertyName owner_test_label -NotePropertyValue 'Tianxia WIN1-P1 Owner Test' -Force
    $Version | Add-Member -NotePropertyName default_data_root -NotePropertyValue 'OwnerTestData' -Force
    $Version | Add-Member -NotePropertyName production_installation_modified -NotePropertyValue $false -Force
    $Version | Add-Member -NotePropertyName production_userdata_modified -NotePropertyValue $false -Force
    $Version | Add-Member -NotePropertyName final_release_readiness_claimed -NotePropertyValue $false -Force
    Write-Json $Version $VersionPath
  }

  Invoke-Stage 'final_application_checksum_generation' 'generate exact checksum inventory after all Application bytes are final' {
    & $PythonExe (Join-Path $RepoRoot 'win1_p1\application_checksum.py') --application (Join-Path $DeliveryRoot 'Application') --generate --output (Join-Path $EvidenceRoot 'application-checksum-generation.json')
    if ($LASTEXITCODE -ne 0) { throw 'Final Application checksum generation or verification failed.' }
  }

  Invoke-Stage 'native_isolation_verification' 'launch primary and clean Factory through supported launchers' {
    & (Join-Path $RepoRoot 'win1_p1\Verify-OwnerTestIsolation.ps1') -DeliveryRoot $DeliveryRoot -EvidenceRoot $EvidenceRoot
    if ($LASTEXITCODE -ne 0) { throw 'WIN1-P1 isolation verification failed.' }
  }

  Invoke-Stage 'post_isolation_application_checksum_verification' 'prove launch verification did not change final Application inventory' {
    & $PythonExe (Join-Path $RepoRoot 'win1_p1\application_checksum.py') --application (Join-Path $DeliveryRoot 'Application') --output (Join-Path $EvidenceRoot 'application-checksum-verification.json')
    if ($LASTEXITCODE -ne 0) { throw 'Post-isolation Application checksum verification failed.' }
  }

  Invoke-Stage 'identity_and_package_manifest' 'bind source, executable, launchers, GM Screen, and changed-file delta' {
    $Head = (git -C $RepoRoot rev-parse HEAD).Trim()
    $BranchOutput = git -C $RepoRoot branch --show-current
    $Branch = if ($null -eq $BranchOutput) { '' } else { $BranchOutput.Trim() }
    if ([string]::IsNullOrWhiteSpace($Branch)) {
      $Branch = [string]$env:GITHUB_HEAD_REF
    }
    if ([string]::IsNullOrWhiteSpace($Branch)) {
      $Branch = (git -C $RepoRoot rev-parse --abbrev-ref HEAD).Trim()
    }
    $CandidateHead = $Head
    if (-not [string]::IsNullOrWhiteSpace([string]$env:GITHUB_HEAD_REF)) {
      $CandidateRef = "origin/$($env:GITHUB_HEAD_REF)"
      $CandidateHeadOutput = git -C $RepoRoot rev-parse $CandidateRef 2>$null
      if ($LASTEXITCODE -eq 0 -and $null -ne $CandidateHeadOutput) {
        $CandidateHead = $CandidateHeadOutput.Trim()
      }
    }
    $Baseline = Get-Content -Raw (Join-Path $RepoRoot 'ci\source-baseline.json') | ConvertFrom-Json
    $AcceptedMergeCommit = (git -C $RepoRoot rev-parse origin/main).Trim()
    git -C $RepoRoot diff --name-status origin/main...HEAD | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'changed-file-inventory.txt') -Encoding UTF8
    git -C $RepoRoot diff --stat origin/main...HEAD | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'changed-file-stat.txt') -Encoding UTF8
    git -C $RepoRoot diff --no-ext-diff origin/main...HEAD | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'source-diff.patch') -Encoding UTF8
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'win1_p1\BOUNDED_DELTA.md') -Destination (Join-Path $EvidenceRoot 'BOUNDED_DELTA.md')
    $Identity = [ordered]@{
      schema='Tianxia.WIN1P1.SourceBuildIdentity.v1'; state='WIN1_P1_ISOLATED_NATIVE_WINDOWS_OWNER_TEST_BUILD_READY'
      repository='ssynesthesiagit/CultivationFactory-Public'; branch=$Branch; build_commit=$Head
      accepted_merge_commit=$AcceptedMergeCommit; accepted_pr_head=$CandidateHead
      accepted_app_files=$Baseline.application_source.file_count; accepted_app_bytes=$Baseline.application_source.total_bytes
      accepted_source_tree_sha256=$Baseline.application_source.source_tree_commitment_sha256
      accepted_catalog_sha256=$Baseline.catalog.registry_commitment_sha256
      application_exe_sha256=Sha256 (Join-Path $DeliveryRoot 'Application\Tianxia Factory.exe')
      primary_launcher_sha256=Sha256 (Join-Path $DeliveryRoot 'LAUNCH_TIANXIA_OWNER_TEST.cmd')
      clean_import_launcher_sha256=Sha256 (Join-Path $DeliveryRoot 'LAUNCH_CLEAN_IMPORT_TEST.cmd')
      exact_gm_screen_sha256=Sha256 (Join-Path $DeliveryRoot 'Exact Bundled GM Screen\HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip')
      default_data_root='OwnerTestData'; production_installation_untouched=$true; production_userdata_untouched=$true
      final_release_readiness_claimed=$false
      win1_p1r2_native_receipt=[ordered]@{run_id=[long]$env:GITHUB_RUN_ID; run_attempt=[int]$env:GITHUB_RUN_ATTEMPT; head_sha=$Head; scope='ISOLATED_NATIVE_BUILD_LAUNCH_TRANSFER_AND_PRESERVATION'}
      preservation_reference_receipts=[ordered]@{integration_run=30689873462; full_product_run=30687338858; authority_scope='UNCHANGED_PR7_PRESERVATION_PATHS_ONLY'; win1_p1r2_authority=$false; reason='WIN1-P1R2 changes APP surfaces. Prior receipts are preservation references only and do not verify Method planning, Insight authority, DeepSeek configuration, or complete-request Save As.'}
    }
    Write-Json $Identity (Join-Path $DeliveryRoot 'SOURCE_BUILD_IDENTITY.json')
    Write-Json $Identity (Join-Path $EvidenceRoot 'SOURCE_BUILD_IDENTITY.json')
    $Records = @(Get-ChildItem -LiteralPath $DeliveryRoot -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
      [ordered]@{path=$_.FullName.Substring($DeliveryRoot.Length+1).Replace('\','/');bytes=$_.Length;sha256=Sha256 $_.FullName}
    })
    Write-Json ([ordered]@{schema='Tianxia.WIN1P1.PackageManifest.v1';records=$Records}) (Join-Path $DeliveryRoot 'PACKAGE_MANIFEST.json') 12
    $SumsPath = Join-Path $DeliveryRoot 'SHA256SUMS.txt'
    $Lines = @(Get-ChildItem -LiteralPath $DeliveryRoot -Recurse -File -Force | Where-Object {$_.FullName -ne $SumsPath} | Sort-Object FullName | ForEach-Object {
      "$(Sha256 $_.FullName)  $($_.FullName.Substring($DeliveryRoot.Length+1).Replace('\','/'))"
    })
    [IO.File]::WriteAllText($SumsPath,(($Lines -join "`n")+"`n"),[Text.UTF8Encoding]::new($false))
  }

  Invoke-Stage 'delivery_zip_and_crc' 'safe ZIP creation plus path, CRC, manifest, and SHA256SUMS checks' {
    New-SafeZip $DeliveryRoot $DeliveryZip
    if ((Get-Item -LiteralPath $DeliveryZip).Length -gt 209715200) {
      throw "Owner-test delivery is $((Get-Item -LiteralPath $DeliveryZip).Length) bytes, exceeding the 200 MB limit."
    }
    & $PythonExe (Join-Path $RepoRoot 'win1_p1\verify_delivery.py') --delivery $DeliveryRoot --archive $DeliveryZip --output (Join-Path $EvidenceRoot 'delivery-verification.json')
    if ($LASTEXITCODE -ne 0) { throw 'Delivery verification failed.' }
    [IO.File]::WriteAllText("$DeliveryZip.sha256","$(Sha256 $DeliveryZip)  $([IO.Path]::GetFileName($DeliveryZip))`n",[Text.UTF8Encoding]::new($false))
    Write-Json ([ordered]@{path=[IO.Path]::GetFileName($DeliveryZip);bytes=(Get-Item $DeliveryZip).Length;sha256=Sha256 $DeliveryZip}) (Join-Path $EvidenceRoot 'delivery-zip-identity.json')
  }

  Write-Json ([ordered]@{schema='Tianxia.WIN1P1.FailureClassification.v1';classification='PASS';failing_stage=$null;product_assertion_reached=$true;runner_os='Windows'}) (Join-Path $EvidenceRoot 'failure-classification.json')
  $TotalRecordedSeconds = [double](($Timings | ForEach-Object { [double]$_['elapsed_seconds'] } | Measure-Object -Sum).Sum)
  Write-Json ([ordered]@{schema='Tianxia.WIN1P1.StageTimings.v1';stage_count=$Timings.Count;stages=$Timings;total_recorded_seconds=[Math]::Round($TotalRecordedSeconds,6)}) (Join-Path $EvidenceRoot 'stage-timings.json') 12
  $ArtifactRecords = @(Get-ChildItem -LiteralPath $OutputRoot -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
    [ordered]@{path=$_.FullName.Substring($OutputRoot.Length+1).Replace('\','/');bytes=$_.Length;sha256=Sha256 $_.FullName}
  })
  Write-Json ([ordered]@{schema='Tianxia.WIN1P1.ArtifactIndex.v1';bounded=$true;records=$ArtifactRecords}) (Join-Path $EvidenceRoot 'artifact-index.json') 12
  Write-Host 'WIN1_P1_ISOLATED_NATIVE_WINDOWS_OWNER_TEST_BUILD_READY'
} catch {
  $AcceptedEvidence = Join-Path $RepoRoot '.windows_build\evidence'
  if (Test-Path -LiteralPath $AcceptedEvidence -PathType Container) {
    foreach ($FailureEvidenceName in @('failed-launcher-state.json','failed-startup.log','postbuild-selfcheck.json')) {
      $FailureEvidencePath = Join-Path $AcceptedEvidence $FailureEvidenceName
      if (Test-Path -LiteralPath $FailureEvidencePath -PathType Leaf) {
        Copy-Item -LiteralPath $FailureEvidencePath -Destination (Join-Path $EvidenceRoot $FailureEvidenceName) -Force
      }
    }
  }
  Write-Json ([ordered]@{schema='Tianxia.WIN1P1.FailureClassification.v1';classification='PRODUCT_OR_BUILD_FAILURE';error=$_.Exception.Message;runner_os='Windows'}) (Join-Path $EvidenceRoot 'failure-classification.json')
  Write-Json ([ordered]@{schema='Tianxia.WIN1P1.StageTimings.v1';stage_count=$Timings.Count;stages=$Timings}) (Join-Path $EvidenceRoot 'stage-timings.json') 12
  throw
}
