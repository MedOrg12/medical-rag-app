@echo off
REM Backup script for Medical Research RAG Pipeline (Windows)
REM Creates timestamped backups of vector database, data cache, and PDFs

setlocal enabledelayedexpansion

REM Configuration
if "%BACKUP_DIR%"=="" set BACKUP_DIR=backups
set TIMESTAMP=%DATE:~-4%%DATE:~4,2%%DATE:~7,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%
set BACKUP_NAME=medical-rag-backup-%TIMESTAMP%
set BACKUP_PATH=%BACKUP_DIR%\%BACKUP_NAME%

echo ╔═══════════════════════════════════════════════════╗
echo ║   Medical Research RAG - Backup Script (Windows) ║
echo ╚═══════════════════════════════════════════════════╝
echo.

REM Create backup directory
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
mkdir "%BACKUP_PATH%"
echo ✓ Created backup directory: %BACKUP_PATH%

REM Function to backup directory
:backup_directory
set SOURCE=%~1
set NAME=%~2

if exist "%SOURCE%" (
    echo → Backing up %NAME%...
    powershell -Command "Compress-Archive -Path '%SOURCE%' -DestinationPath '%BACKUP_PATH%\%NAME%.zip' -Force"
    echo ✓ %NAME% backed up
) else (
    echo ⚠ %NAME% doesn't exist, skipping
)
goto :eof

REM Backup vector database
call :backup_directory "vector_db" "vector_db"

REM Backup data cache
call :backup_directory "data" "data"

REM Backup PDFs
call :backup_directory "pdfs" "pdfs"

REM Backup logs from Docker volume
echo → Backing up logs from Docker volume...
docker run --rm -v logs_data:/logs -v "%BACKUP_PATH%":/backup alpine tar -czf /backup/logs.tar.gz -C / logs 2>nul || echo ⚠ No logs volume found, skipping

REM Backup configuration files
echo → Backing up configuration files...
if exist ".env" copy ".env" "%BACKUP_PATH%\.env" >nul
copy "docker-compose.yml" "%BACKUP_PATH%\docker-compose.yml" >nul
copy "requirements.txt" "%BACKUP_PATH%\requirements.txt" >nul
echo ✓ Configuration files backed up

REM Create metadata file
(
echo Medical Research RAG - Backup Metadata
echo ======================================
echo Backup Date: %DATE% %TIME%
echo Computer: %COMPUTERNAME%
echo Backup Path: %BACKUP_PATH%
echo.
echo Contents:
if exist "%BACKUP_PATH%\vector_db.zip" (echo - Vector Database: Yes) else (echo - Vector Database: No)
if exist "%BACKUP_PATH%\data.zip" (echo - Data Cache: Yes) else (echo - Data Cache: No)
if exist "%BACKUP_PATH%\pdfs.zip" (echo - PDFs: Yes) else (echo - PDFs: No)
if exist "%BACKUP_PATH%\logs.zip" (echo - Logs: Yes) else (echo - Logs: No)
) > "%BACKUP_PATH%\backup-metadata.txt"

echo ✓ Metadata file created
echo.
echo ╔═══════════════════════════════════════════════════╗
echo ║   Backup completed successfully!                 ║
echo ╚═══════════════════════════════════════════════════╝
echo.
echo Backup Location: %BACKUP_PATH%
echo.
echo To restore this backup, run:
echo   scripts\restore.bat %BACKUP_NAME%
echo.

pause
