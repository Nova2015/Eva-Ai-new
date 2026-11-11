@echo off
title EVA AI - Starting Services
color 0A

echo ========================================
echo        EVA AI SERVICES STARTING
echo ========================================
echo.

echo [1/2] Starting RAG Service - Port 8000...
set "COGNITIVE_DRIVER_ENABLED=true"
start "EVA RAG - 8000" /D "D:\Eva_Ai_brain" cmd /k ".venv\Scripts\python.exe -m uvicorn src.app:app --reload"

timeout /t 2 /nobreak >nul

echo [2/2] Starting ML Service - Port 7860...
start "EVA ML - 7860" /D "D:\Eva_Ai_brain\eva-ml-service" cmd /k ".venv\Scripts\python.exe app.py"

echo.
echo ========================================
echo        EVA AI SERVICES STARTED
echo ========================================
echo.
echo RAG     : http://127.0.0.1:8000
echo ML      : http://127.0.0.1:7860
echo Ollama  : Already running
echo.
echo ========================================
pause
