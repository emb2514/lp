@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    echo ============================================================
    echo  Lender Package Builder
    echo ============================================================
    echo.
    echo Drag a ZIP file, folder, or supported document onto this file
    echo to build a lender package, or run it from a command prompt:
    echo.
    echo     RUN_STAGE1.bat "C:\path\to\your\lender_package.zip"
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
echo  Lender Package Builder - Building your package
echo ============================================================
echo Input: %~1
echo.

".venv\Scripts\python.exe" -m lender_package_builder build %*

set "RESULT=%errorlevel%"
echo.
if "%RESULT%"=="0" (
    echo Done. A new output folder was created next to your input,
    echo named "..._Lender_Package_Output_<date>_<time>". Open its
    echo Reports folder and read Processing_Report.txt first.
) else (
    echo The build did not finish successfully. Scroll up in this
    echo window to see why, and check the Reports folder inside the
    echo output folder if one was created.
)
echo.
pause
exit /b %RESULT%
