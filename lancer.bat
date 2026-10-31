@echo off
cd /d "%~dp0"
echo ==================================================
echo   Memoire des Anciens - Demarrage du serveur
echo ==================================================
echo.
if not exist ".venv\Scripts\python.exe" (
    echo Environnement Python introuvable. Creez-le avec :
    echo   py -3.13 -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
".venv\Scripts\python.exe" main.py
pause
