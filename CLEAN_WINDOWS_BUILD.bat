@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Lender Package Builder - Clean Build Artifacts
echo ============================================================
echo.
echo This removes PyInstaller's build output and caches so the next
echo BUILD_WINDOWS_PORTABLE.bat run starts completely fresh. It does
echo NOT touch your .venv, source code, or any of your own files.
echo.

if exist "build" (
    echo Removing build\ ...
    rmdir /s /q "build"
)
if exist "dist" (
    echo Removing dist\ ...
    rmdir /s /q "dist"
)
if exist "release" (
    echo Removing release\ ...
    rmdir /s /q "release"
)
if exist "packaging\version_info.txt" (
    echo Removing packaging\version_info.txt (regenerated on every build) ...
    del /f /q "packaging\version_info.txt"
)
if exist ".pytest_cache" (
    echo Removing .pytest_cache\ ...
    rmdir /s /q ".pytest_cache"
)

echo.
echo Removing __pycache__ folders...
for /d /r %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d"
)

echo.
echo ============================================================
echo  Clean complete.
echo ============================================================
echo.
echo Note: packaging\app_icon.ico was left in place (it only depends
echo on app_icon.svg and is regenerated automatically if that source
echo file changes). Delete it by hand if you want to force a rebuild.
echo.
pause
exit /b 0
