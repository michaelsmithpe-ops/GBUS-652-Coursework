@echo off
rem Fort GBUS Counter-Drone Decision Aid - one-click start (Windows).
rem Sets up Python packages, builds the rules database if missing, and opens the web page.
rem This file never calls Claude. Real runs (which cost money) are started from the page and
rem need an Anthropic API key in API-Key.txt in the folder above the repository.

setlocal
cd /d "%~dp0.."
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo Creating the Python environment .venv ...
    py -3.13 -m venv .venv 2>nul || python -m venv .venv
    if not exist "%PY%" (
        echo Could not create .venv. Please install Python 3.13 from python.org and try again.
        pause
        exit /b 1
    )
)

echo Checking the Python packages ...
"%PY%" -m pip install --quiet --disable-pip-version-check -r capstone\requirements.txt
if errorlevel 1 (
    echo Package installation failed. See the messages above.
    pause
    exit /b 1
)

if not exist "capstone\app\chroma_rules" (
    echo Building the rules database ^(first run only^) ...
    "%PY%" capstone\app\fgb_rules.py --rebuild
    if errorlevel 1 (
        echo Building the rules database failed. See the messages above.
        pause
        exit /b 1
    )
)

echo.
echo Starting the web page at http://localhost:8501  (close this window to stop it)
start "" cmd /c "timeout /t 6 /nobreak >nul & start http://localhost:8501"
"%PY%" -m streamlit run capstone\app\viewer.py --server.headless true --server.address localhost --browser.gatherUsageStats false
pause
