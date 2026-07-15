@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   Lender Package Builder - Build Portable Windows Release
echo ============================================================
echo.
echo This will, on THIS computer only:
echo   1. Create/reuse a private virtual environment in .venv
echo   2. Install build dependencies (including PyInstaller)
echo   3. Run the FULL automated test suite - the build stops here
echo      if anything fails
echo   4. Build a portable, one-folder LenderPackageBuilder.exe with
echo      PyInstaller (no installer, no admin rights, no UPX)
echo   5. Assemble a release folder next to the .exe with config.toml,
echo      the sample test package, and the release documentation
echo   6. Zip the release folder and compute its SHA-256 checksum
echo.

rem ------------------------------------------------------------------
rem 1. Find a supported Python and create/reuse .venv
rem ------------------------------------------------------------------
set "PYCMD="
call :TRY_CANDIDATE "python" && goto :FOUND
call :TRY_CANDIDATE "py -3.13" && goto :FOUND
call :TRY_CANDIDATE "py -3.12" && goto :FOUND
call :TRY_CANDIDATE "py -3.11" && goto :FOUND
call :TRY_CANDIDATE "python3" && goto :FOUND

echo.
echo ERROR: No supported Python installation (3.11-3.13) was found.
echo Install Python from https://www.python.org/downloads/ and try again.
pause
exit /b 1

:FOUND
echo Found a supported Python: !PYCMD!
echo.

if exist ".venv\Scripts\python.exe" (
    echo Reusing existing virtual environment in .venv
) else (
    echo Creating a private virtual environment in .venv ...
    !PYCMD! -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

rem ------------------------------------------------------------------
rem 2. Install build dependencies
rem ------------------------------------------------------------------
echo.
echo Installing build dependencies (this can take a few minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements-windows-build.txt
if errorlevel 1 (
    echo ERROR: Failed to install build dependencies.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install -e . --quiet
if errorlevel 1 (
    echo ERROR: Failed to install the Lender Package Builder application.
    pause
    exit /b 1
)

rem ------------------------------------------------------------------
rem 3. Run the full test suite -- the build does not continue if this fails
rem ------------------------------------------------------------------
echo.
echo ============================================================
echo  Running the full automated test suite before building...
echo ============================================================
".venv\Scripts\python.exe" -m pytest tests -q
if errorlevel 1 (
    echo.
    echo ============================================================
    echo  TESTS FAILED - the portable build was NOT created.
    echo ============================================================
    echo A release must never be built on top of failing tests.
    pause
    exit /b 1
)
echo.
echo All tests passed.

rem ------------------------------------------------------------------
rem 4. Read the single-source version string for naming the release
rem ------------------------------------------------------------------
for /f "usebackq delims=" %%v in (`".venv\Scripts\python.exe" -c "from lender_package_builder._version import RELEASE_LABEL; print(RELEASE_LABEL)"`) do set "RELEASE_LABEL=%%v"
if "%RELEASE_LABEL%"=="" (
    echo ERROR: Could not read the application version.
    pause
    exit /b 1
)
echo.
echo Building release: %RELEASE_LABEL%

rem ------------------------------------------------------------------
rem 5. Regenerate the multi-resolution .ico from the source SVG
rem ------------------------------------------------------------------
".venv\Scripts\python.exe" "packaging\generate_icon.py"
if errorlevel 1 (
    echo ERROR: Failed to generate the application icon.
    pause
    exit /b 1
)

rem ------------------------------------------------------------------
rem 6. Build with PyInstaller (--onedir, no UPX, windowed)
rem ------------------------------------------------------------------
echo.
echo ============================================================
echo  Building the portable executable with PyInstaller...
echo ============================================================
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

".venv\Scripts\python.exe" -m PyInstaller "LenderPackageBuilder.spec" --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

if not exist "dist\LenderPackageBuilder\LenderPackageBuilder.exe" (
    echo ERROR: Build did not produce LenderPackageBuilder.exe.
    pause
    exit /b 1
)

rem ------------------------------------------------------------------
rem 7. Assemble the release folder
rem ------------------------------------------------------------------
echo.
echo Assembling the release folder...
set "RELEASE_NAME=Lender_Package_Builder_%RELEASE_LABEL%_Windows_x64"
set "RELEASE_DIR=release\%RELEASE_NAME%"
if exist "%RELEASE_DIR%" rmdir /s /q "%RELEASE_DIR%"
mkdir "%RELEASE_DIR%"

xcopy /e /i /q "dist\LenderPackageBuilder\*" "%RELEASE_DIR%\" >nul
if errorlevel 1 (
    echo ERROR: Failed to copy the built application into the release folder.
    pause
    exit /b 1
)

copy /y "config.toml" "%RELEASE_DIR%\config.toml" >nul
copy /y "RUN_DIAGNOSTICS.bat" "%RELEASE_DIR%\" >nul
if exist "README_PORTABLE.txt" copy /y "README_PORTABLE.txt" "%RELEASE_DIR%\" >nul
if exist "RELEASE_NOTES_1.0.0_RC1.md" copy /y "RELEASE_NOTES_1.0.0_RC1.md" "%RELEASE_DIR%\" >nul
if exist "THIRD_PARTY_NOTICES.txt" copy /y "THIRD_PARTY_NOTICES.txt" "%RELEASE_DIR%\" >nul
if exist "WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md" copy /y "WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md" "%RELEASE_DIR%\" >nul
if exist "PACKAGING_TROUBLESHOOTING.md" copy /y "PACKAGING_TROUBLESHOOTING.md" "%RELEASE_DIR%\" >nul
if exist "samples\Sample_Test_Package.zip" copy /y "samples\Sample_Test_Package.zip" "%RELEASE_DIR%\" >nul
if exist "samples\Sample_Test_Package_Expected_Results.txt" copy /y "samples\Sample_Test_Package_Expected_Results.txt" "%RELEASE_DIR%\" >nul

echo Collecting third-party license files...
".venv\Scripts\python.exe" "packaging\collect_licenses.py" "%RELEASE_DIR%"
if errorlevel 1 (
    echo ERROR: Failed to collect third-party license files.
    pause
    exit /b 1
)

rem ------------------------------------------------------------------
rem 8. Write a build manifest (date, versions, environment)
rem ------------------------------------------------------------------
echo Lender Package Builder - Build Manifest > "%RELEASE_DIR%\BUILD_MANIFEST.txt"
echo ======================================== >> "%RELEASE_DIR%\BUILD_MANIFEST.txt"
echo Release: %RELEASE_LABEL% >> "%RELEASE_DIR%\BUILD_MANIFEST.txt"
echo Build date/time (local): %DATE% %TIME% >> "%RELEASE_DIR%\BUILD_MANIFEST.txt"
echo. >> "%RELEASE_DIR%\BUILD_MANIFEST.txt"
echo -- Python -- >> "%RELEASE_DIR%\BUILD_MANIFEST.txt"
".venv\Scripts\python.exe" --version >> "%RELEASE_DIR%\BUILD_MANIFEST.txt" 2>&1
echo. >> "%RELEASE_DIR%\BUILD_MANIFEST.txt"
echo -- Installed packages (pip freeze) -- >> "%RELEASE_DIR%\BUILD_MANIFEST.txt"
".venv\Scripts\python.exe" -m pip freeze >> "%RELEASE_DIR%\BUILD_MANIFEST.txt"
echo. >> "%RELEASE_DIR%\BUILD_MANIFEST.txt"
echo -- Git commit -- >> "%RELEASE_DIR%\BUILD_MANIFEST.txt"
git rev-parse HEAD >> "%RELEASE_DIR%\BUILD_MANIFEST.txt" 2>&1

rem ------------------------------------------------------------------
rem 9. Zip the release folder and compute its SHA-256 checksum
rem ------------------------------------------------------------------
echo.
echo Zipping the release and computing its SHA-256 checksum...
set "ZIP_PATH=release\%RELEASE_NAME%_Portable.zip"
set "SHA256_PATH=release\%RELEASE_NAME%_Portable_SHA256.txt"
if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%"
if exist "%SHA256_PATH%" del /f /q "%SHA256_PATH%"

powershell -NoProfile -Command "Compress-Archive -Path '%RELEASE_DIR%\*' -DestinationPath '%ZIP_PATH%' -CompressionLevel Optimal"
if errorlevel 1 (
    echo ERROR: Failed to zip the release folder.
    pause
    exit /b 1
)

powershell -NoProfile -Command "(Get-FileHash -Path '%ZIP_PATH%' -Algorithm SHA256).Hash + '  ' + (Split-Path '%ZIP_PATH%' -Leaf) | Out-File -FilePath '%SHA256_PATH%' -Encoding ascii"
if errorlevel 1 (
    echo ERROR: Failed to compute the SHA-256 checksum.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  BUILD COMPLETE
echo ============================================================
echo.
echo Portable app folder: %RELEASE_DIR%
echo Zipped release:       %ZIP_PATH%
echo SHA-256 checksum:     %SHA256_PATH%
echo.
echo Next: run TEST_PORTABLE_APP.bat to verify the built .exe on its
echo own, without needing Python or pytest installed.
echo.
pause
exit /b 0

rem ------------------------------------------------------------------
rem Tries one Python candidate command. Sets PYCMD and returns 0 if it
rem exists AND its version is >=3.11 and <3.14. Returns 1 otherwise.
rem ------------------------------------------------------------------
:TRY_CANDIDATE
set "CANDIDATE=%~1"
%CANDIDATE% -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>nul
if errorlevel 1 (
    exit /b 1
)
set "PYCMD=%CANDIDATE%"
exit /b 0
