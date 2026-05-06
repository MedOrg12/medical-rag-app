@echo off
REM Medical Research RAG - Ingestion Debugging Script
REM This script helps diagnose ingestion issues

echo.
echo ========================================
echo  Ingestion Debugging Tool
echo ========================================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running!
    pause
    exit /b 1
)

echo [1/7] Checking containers...
docker compose ps
echo.

echo [2/7] Checking PDFs folder...
if exist "pdfs\" (
    echo PDFs folder exists
    dir pdfs\*.pdf /b 2>nul | find /c /v "" > temp_count.txt
    set /p PDF_COUNT=<temp_count.txt
    del temp_count.txt
    echo Found PDFs in folder
    dir pdfs\*.pdf /b 2>nul
) else (
    echo [WARNING] PDFs folder not found!
)
echo.

echo [3/7] Checking Ollama connection...
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Cannot connect to Ollama at localhost:11434
    echo Try restarting Ollama container:
    echo   docker compose restart ollama
) else (
    echo Ollama is accessible
)
echo.

echo [4/7] Checking models...
docker compose exec -T ollama ollama list
echo.

echo [5/7] Checking web server...
curl -s http://localhost:8000/health
echo.
echo.

echo [6/7] Checking RAG app logs (last 50 lines)...
echo Look for errors related to ingestion:
echo.
docker compose logs rag-app --tail=50
echo.

echo [7/7] Checking for common issues...
echo.

REM Check file permissions
echo Checking if app can access pdfs folder...
docker compose exec -T rag-app ls -la /app/pdfs 2>nul
if errorlevel 1 (
    echo [WARNING] Cannot access pdfs folder in container
)
echo.

echo ========================================
echo  Debug Information Complete
echo ========================================
echo.
echo Common Issues:
echo   1. Models not downloaded - Run DOWNLOAD_MODELS.bat
echo   2. Ollama not responding - Restart: docker compose restart ollama
echo   3. File permissions - Check pdfs folder is accessible
echo   4. Path issues - Ensure PDFs are in pdfs\ folder (not subfolders)
echo.
echo To see live ingestion logs, run:
echo   docker compose logs -f rag-app
echo.
pause
