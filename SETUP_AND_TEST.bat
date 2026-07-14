@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   Lender Package Builder - Setup and Test  (Stage 1)
echo ============================================================
echo.
echo This will, on THIS computer only:
echo   1. Look for a supported Python (3.11, 3.12, or 3.13)
echo   2. Create a private virtual environment in this folder ^(.venv^)
echo   3. Install the required packages into that environment only
echo   4. Run the automated test suite and show you the results
echo.
echo No administrator rights are needed and nothing is installed
echo system-wide or outside this folder.
echo.

set "PYCMD="

call :TRY_CANDIDATE "python" && goto :FOUND
call :TRY_CANDIDATE "py -3.13" && goto :FOUND
call :TRY_CANDIDATE "py -3.12" && goto :FOUND
call :TRY_CANDIDATE "py -3.11" && goto :FOUND
call :TRY_CANDIDATE "python3" && goto :FOUND

echo.
echo ============================================================
echo  ERROR: No supported Python installation was found.
echo ============================================================
echo.
echo This tool needs Python 3.11, 3.12, or 3.13 ^(64-bit^).
echo.
echo 1. Go to https://www.python.org/downloads/
echo 2. Download the latest Python 3.13 installer for Windows.
echo 3. Run it and check "Add python.exe to PATH."
echo 4. You do NOT need administrator rights - "Install for me only"
echo    is fine if you are asked.
echo 5. Run this SETUP_AND_TEST.bat file again.
echo.
pause
exit /b 1

:FOUND
echo.
echo Found a supported Python: !PYCMD!
echo.

if exist ".venv\Scripts\python.exe" (
    echo A virtual environment already exists in .venv - reusing it.
) else (
    echo Creating a private virtual environment in .venv ...
    !PYCMD! -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

echo.
echo Installing required packages ^(this can take a few minutes the
echo first time - it needs an internet connection^)...
echo.

".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip inside the virtual environment.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install required packages.
    echo Check your internet connection and try again.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install -e . --quiet
if errorlevel 1 (
    echo ERROR: Failed to install the Lender Package Builder application.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Running the automated test suite...
echo ============================================================
echo.

".venv\Scripts\python.exe" -m pytest tests -v
set "TEST_RESULT=%errorlevel%"

echo.
echo ============================================================
if "%TEST_RESULT%"=="0" (
    echo  ALL TESTS PASSED
    echo ============================================================
    echo.
    echo Setup is complete and the application is working correctly
    echo on this computer.
    echo.
    echo Next: open FIRST_TEST_INSTRUCTIONS.md for a simple walkthrough
    echo of building your first test package.
) else (
    echo  SOME TESTS FAILED  ^(see the output above for details^)
    echo ============================================================
    echo.
    echo Please copy this window's text and report it back to Claude
    echo Code so it can help fix the problem.
)
echo.
pause
exit /b %TEST_RESULT%

rem ------------------------------------------------------------------
rem Tries one Python candidate command. Sets PYCMD and returns 0 (via
rem exit /b 0) if it exists AND its version is >=3.11 and <3.14.
rem Returns 1 (exit /b 1) otherwise, leaving PYCMD untouched.
rem ------------------------------------------------------------------
:TRY_CANDIDATE
set "CANDIDATE=%~1"
%CANDIDATE% -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>nul
if errorlevel 1 (
    exit /b 1
)
set "PYCMD=%CANDIDATE%"
exit /b 0
