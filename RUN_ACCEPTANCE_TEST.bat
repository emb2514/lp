@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    echo ============================================================
    echo  Lender Package Builder - Acceptance Test
    echo ============================================================
    echo.
    echo This runs the exact same production process as RUN_STAGE1.bat,
    echo using only the default settings from config.toml, so you can
    echo confirm the application handles a real lender ZIP correctly.
    echo.
    echo IMPORTANT: Use a COPY of a lender ZIP, never your only copy,
    echo and only use files you are authorized to process on this
    echo computer.
    echo.
    echo Drag a lender ZIP file onto this file, or run:
    echo     RUN_ACCEPTANCE_TEST.bat "C:\path\to\lender_package.zip"
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo ============================================================
    echo  ERROR: Setup has not been run yet.
    echo ============================================================
    echo.
    echo Please double-click SETUP_AND_TEST.bat first, wait for it to
    echo finish successfully, and then try this again.
    echo.
    pause
    exit /b 1
)

echo ============================================================
echo  Lender Package Builder - Acceptance Test
echo ============================================================
echo Input: %~1
echo Using the default configuration in config.toml ^(no overrides^)
echo.

".venv\Scripts\python.exe" -m lender_package_builder build "%~1"

set "RESULT=%errorlevel%"
echo.
if "%RESULT%"=="0" (
    echo ACCEPTANCE TEST PASSED.
    echo Review the output folder created next to your input file,
    echo especially Reports\Processing_Report.txt, before trusting
    echo this on real lender packages.
) else (
    echo ACCEPTANCE TEST FAILED.
    echo Scroll up in this window to see why, check the Reports
    echo folder if one was created, and report this back to Claude
    echo Code.
)
echo.
pause
exit /b %RESULT%
