@echo off
setlocal
cd /d "%~dp0"

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
echo  Lender Package Builder - Starting the desktop application...
echo ============================================================
echo.
echo A window should appear in a moment. You can close this black
echo window once the application window is open - it is only shown
echo here so you can see any error messages if something goes wrong.
echo.

".venv\Scripts\pythonw.exe" -m lender_package_builder.gui
if errorlevel 1 (
    echo.
    echo The application did not start correctly using pythonw.exe.
    echo Trying again with python.exe so any error message is visible...
    echo.
    ".venv\Scripts\python.exe" -m lender_package_builder.gui
    if errorlevel 1 (
        echo.
        echo ============================================================
        echo  ERROR: The application failed to start.
        echo ============================================================
        echo.
        echo Please copy the text above and report it back to Claude Code.
        echo.
        pause
        exit /b 1
    )
)

exit /b 0
