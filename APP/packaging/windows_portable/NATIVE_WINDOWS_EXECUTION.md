# M1 Native Windows Build Execution

This merged M1 source was prepared and checked outside Windows. No newly compiled EXE,
installer, native WebView2 acceptance, or owner acceptance is claimed.

## Required environment

- Native Windows 10 or 11 x64.
- Python 3.12 x64 from python.org.
- PowerShell 5.1 or newer.
- Microsoft Edge WebView2 Runtime.
- Internet access for pinned build packages and the pinned CPython embeddable
  runtime.
- Exact Factory input `Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip`, SHA-256
  `4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385`.
- Exact Foundation input `Tianxia_Foundation_FactoryApp_Handoff_v1_0.zip`,
  SHA-256
  `df80217c64c0808190c85531095e5e78aa96ff6808be369915f36fbb4189771c`.
- The prepared `Inputs/PrivateRuntimeWheels` wheelhouse.

The M1 programming handoff did not contain those three external build inputs.
Place them beside the extracted source as described below; do not substitute or
reconstruct them.

## Layout

```text
M1_Windows_Build/
  BUILD_M1_ON_NATIVE_WINDOWS.ps1
  Source/                         # extracted corrected full source
  Inputs/
    Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip
    Tianxia_Foundation_FactoryApp_Handoff_v1_0.zip
    PrivateRuntimeWheels/
```

The consolidated M1 delivery includes a ready wrapper and a source ZIP. Extract
the source ZIP into `Source`, place the exact inputs under `Inputs`, then run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\BUILD_M1_ON_NATIVE_WINDOWS.ps1 -VerifyOnly
.\BUILD_M1_ON_NATIVE_WINDOWS.ps1
```

The wrapper validates the layout and delegates to
`Source\packaging\windows_portable\Build-WindowsPortable.ps1`.

A successful full run writes an M1 portable build and native evidence with
SHA-256 sidecars. Do not call it owner-accepted unless interactive native
acceptance actually runs and `windows-desktop-window-acceptance.json` says
`PASS`. The manual W1 checklist remains separate.
