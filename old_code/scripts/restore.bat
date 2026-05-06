@echo off
REM Restore script for Medical Research RAG Pipeline (Windows)
REM Restores vector database, data cache, and PDFs from backup

setlocal enabledelayedexpansion

REM Configuration
if "%BACKUP_DIR%"=="" set BACKUP_DIR=backups

echo ╔═══════════════════════════════════════════════════╗
echo ║   Medical Research RAG - Restore Script (Windows)║
echo ╚═══════════════════════════════════════════════════╝
echo.

REM Check if backup name provided
if "%1"=="" (
    echo Available backups:
    dir /b "%BACKUP_DIR%\medical-rag-backup-*" 2>nul || echo No backups found
    echo.
    echo Usage: %0 ^<backup-name^>
    echo Example: %0 medical-rag-backup-20260311_143000
    pause
    exit /b 1
)

set BACKUP_NAME=%1
set BACKUP_PATH=%BACKUP_DIR%\%BACKUP_NAME%

REM Check if backup exists
if not exist "%BACKUP_PATH%" (
    echo ✗ Backup not found: %BACKUP_PATH%
    pause
    exit /b 1
)

echo ✓ Found backup: %BACKUP_PATH%

REM Display backup metadata
if exist "%BACKUP_PATH%\backup-metadata.txt" (
    echo.
    echo Backup Information:
    type "%BACKUP_PATH%\backup-metadata.txt"
    echo.
)

REM Confirm restoration
echo ⚠ WARNING: This will replace existing data!
set /p CONFIRM=Continue with restoration? (yes/no):
if /i not "%CONFIRM%"=="yes" (
    echo Restoration cancelled
    pause
    exit /b 0
)

REM Stop running containers
echo → Stopping running containers...
docker compose down 2>nul || docker-compose down 2>nul || echo ⚠ No containers to stop

REM Function to restore directory
:restore_directory
set ARCHIVE=%BACKUP_PATH%\%~1.zip
set TARGET=%~2
set NAME=%~1

if exist "%ARCHIVE%" (
    echo → Restoring %NAME%...

    REM Backup existing directory
    if exist "%TARGET%" (
        echo   ↳ Backing up existing %NAME% to %TARGET%.old
        if exist "%TARGET%.old" rmdir /s /q "%TARGET%.old"
        move "%TARGET%" "%TARGET%.old" >nul
    )

    REM Extract archive
    powershell -Command "Expand-Archive -Path '%ARCHIVE%' -DestinationPath '.' -Force"
    echo ✓ %NAME% restored
) else (
    echo ⚠ No %NAME% backup found, skipping
)
goto :eof

REM Restore vector database
call :restore_directory "vector_db" "vector_db"

REM Restore data cache
call :restore_directory "data" "data"

REM Restore PDFs
call :restore_directory "pdfs" "pdfs"

REM Restore logs
call :restore_directory "logs" "logs"

REM Restore configuration files
echo → Restoring configuration files...
if exist "%BACKUP_PATH%\.env" (
    copy "%BACKUP_PATH%\.env" ".env" >nul
    echo ✓ .env restored
)
if exist "%BACKUP_PATH%\docker-compose.yml" (
    if exist "docker-compose.yml" copy "docker-compose.yml" "docker-compose.yml.backup" >nul
    echo   ↳ docker-compose.yml backed up (you may want to review changes)
)

echo.
echo ╔═══════════════════════════════════════════════════╗
echo ║   Restoration completed successfully!            ║
echo ╚═══════════════════════════════════════════════════╝
echo.
echo Next steps:
echo   1. Review configuration files if needed
echo   2. Start the application: docker compose up -d
echo.
echo Note: Old data backed up to *.old directories
echo.

pause
