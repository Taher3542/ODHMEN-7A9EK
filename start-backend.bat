@echo off
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo Impossible de creer l'environnement Python. Installez Python 3.12.
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Echec de l'installation des dependances backend.
        pause
        exit /b 1
    )
)
if not exist .env copy .env.example .env
echo.
echo Backend ODHMEN 7A9EK : http://127.0.0.1:8001
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
pause
