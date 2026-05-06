@echo off
REM
REM Build script for Windows .exe
REM Creates a native Windows executable with PyInstaller
REM
REM Usage:
REM   build_windows.bat
REM
REM Output:
REM   dist\MedicalRAG.exe - Windows executable
REM   dist\MedicalRAG-Setup-v1.0.0.exe - Installer (if Inno Setup is configured)
REM

setlocal

set VERSION=1.0.0
set APP_NAME=MedicalRAG

echo ==========================================
echo Building Medical RAG for Windows
echo Version: %VERSION%
echo ==========================================
echo.

REM Check if virtual environment exists
if not exist "venv" (
    echo Virtual environment not found
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install/upgrade production dependencies
echo Installing production dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements-prod.txt

REM Clean previous builds
echo Cleaning previous builds...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

REM Run PyInstaller
echo.
echo Running PyInstaller...
pyinstaller build_windows.spec

REM Check if build succeeded
if not exist "dist\%APP_NAME%\%APP_NAME%.exe" (
    echo.
    echo Build failed - executable not found
    exit /b 1
)

echo.
echo Build successful!
echo    Executable: dist\%APP_NAME%\%APP_NAME%.exe
echo.

REM TODO: Add Inno Setup script for creating installer
echo To create an installer, use Inno Setup with a custom script
echo.

echo ==========================================
echo Build Complete!
echo ==========================================
echo.
echo To test the application:
echo   dist\%APP_NAME%\%APP_NAME%.exe
echo.
echo Note: Make sure Ollama is installed:
echo   Download from https://ollama.com/download
echo.

endlocal
