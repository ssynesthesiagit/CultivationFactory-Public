@echo off
setlocal
set "TIANXIA_FOUNDRY_DATA=%~dp0OwnerTestData"
set "TIANXIA_WINDOW_TITLE=Tianxia Current Owner Test"
if not exist "%TIANXIA_FOUNDRY_DATA%" mkdir "%TIANXIA_FOUNDRY_DATA%"
"%~dp0Tianxia Factory.exe"
endlocal
