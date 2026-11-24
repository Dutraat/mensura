@echo off
chcp 65001 >nul
title Mensura — Servidor Local (Windows)
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual Python...
    python -m venv .venv
)

echo Instalando/verificando dependencias do backend...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

echo.
echo Iniciando Mensura em http://127.0.0.1:8000 ...
start "" "http://127.0.0.1:8000"
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
pause
