@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   Lender Package Builder - Test the Built Portable App
echo ============================================================
echo.
echo This runs the ALREADY-BUILT LenderPackageBuilder.exe through its
echo packaged --version / --self-test / --diagnostics / --gui-smoke-test
echo checks. It does NOT use Python, pip, or pytest from this machine
echo at all -- it only runs the .exe itself, exactly like a lender's
echo locked-down computer would. If this passes, the build is
echo self-contained.
echo.

set "EXE_PATH="
for /f "delims=" %%f in ('dir /b /s /o-d "release\Lender_Package_Builder_*\LenderPackageBuilder.exe" 2^>nul') do (
    if not defined EXE_PATH set "EXE_PATH=%%f"
)
if not defined EXE_PATH (
    if exist "dist\LenderPackageBuilder\LenderPackageBuilder.exe" (
        set "EXE_PATH=dist\LenderPackageBuilder\LenderPackageBuilder.exe"
    )
)

if not defined EXE_PATH (
    echo ERROR: No built LenderPackageBuilder.exe was found.
    echo Run BUILD_WINDOWS_PORTABLE.bat first.
    pause
    exit /b 1
)

echo Testing: %EXE_PATH%
echo.

set "OVERALL_RESULT=0"

echo ------------------------------------------------------------
echo  --version
echo ------------------------------------------------------------
"%EXE_PATH%" --version
if errorlevel 1 (
    echo [FAIL] --version returned a non-zero exit code.
    set "OVERALL_RESULT=1"
) else (
    echo [OK] --version
)
echo.

echo ------------------------------------------------------------
echo  --self-test  (runs a real, self-contained build in a temp folder)
echo ------------------------------------------------------------
"%EXE_PATH%" --self-test
if errorlevel 1 (
    echo [FAIL] --self-test reported a failure.
    set "OVERALL_RESULT=1"
) else (
    echo [OK] --self-test
)
echo.

echo ------------------------------------------------------------
echo  --diagnostics
echo ------------------------------------------------------------
"%EXE_PATH%" --diagnostics
if errorlevel 1 (
    echo [FAIL] --diagnostics returned a non-zero exit code.
    set "OVERALL_RESULT=1"
) else (
    echo [OK] --diagnostics
)
echo.

echo ------------------------------------------------------------
echo  --gui-smoke-test  (opens and closes the real application window)
echo ------------------------------------------------------------
"%EXE_PATH%" --gui-smoke-test
if errorlevel 1 (
    echo [FAIL] --gui-smoke-test reported a failure.
    set "OVERALL_RESULT=1"
) else (
    echo [OK] --gui-smoke-test
)
echo.

echo ============================================================
if "%OVERALL_RESULT%"=="0" (
    echo  ALL PORTABLE APP CHECKS PASSED
    echo ============================================================
    echo.
    echo The built .exe is self-contained and functional on this
    echo machine. This does NOT replace the manual acceptance test in
    echo WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md, which also exercises the
    echo real user interface with your own eyes.
) else (
    echo  ONE OR MORE CHECKS FAILED - see the output above
    echo ============================================================
    echo.
    echo Please copy this window's text and report it back to Claude
    echo Code so it can help fix the problem.
)
echo.
pause
exit /b %OVERALL_RESULT%
