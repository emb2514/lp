@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   Lender Package Builder - Diagnostics
echo ============================================================
echo.
echo This prints information about this computer and this install
echo that can help troubleshoot a problem: version, whether the
echo document conversion tools (LibreOffice / Microsoft Office) were
echo found, disk space, and installed component versions. Nothing
echo here is sent anywhere -- it is only shown on screen and saved to
echo a text file you can share.
echo.

set "EXE_PATH="
if exist "%~dp0LenderPackageBuilder.exe" (
    set "EXE_PATH=%~dp0LenderPackageBuilder.exe"
) else (
    for /f "delims=" %%f in ('dir /b /s /o-d "release\Lender_Package_Builder_*\LenderPackageBuilder.exe" 2^>nul') do (
        if not defined EXE_PATH set "EXE_PATH=%%f"
    )
)

if not defined EXE_PATH (
    echo ERROR: Could not find LenderPackageBuilder.exe.
    echo Run this file either from inside the installed application
    echo folder, or from the repository root after BUILD_WINDOWS_PORTABLE.bat.
    pause
    exit /b 1
)

"%EXE_PATH%" --diagnostics

echo.
pause
exit /b 0
