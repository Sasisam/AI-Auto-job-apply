@echo off
cd /d %~dp0
set PY=python
where python >nul 2>nul || set PY=py -3
if not exist .venv (
  echo First run: installing JobPilot, this takes a few minutes...
  %PY% -m venv .venv
  call .venv\Scripts\activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  playwright install chromium
  copy requirements.txt .venv\req.stamp >nul
) else (
  call .venv\Scripts\activate
  fc requirements.txt .venv\req.stamp >nul 2>nul || (pip install -r requirements.txt && copy /y requirements.txt .venv\req.stamp >nul)
)
if not exist .env copy .env.example .env
echo.
echo JobPilot is running at http://127.0.0.1:8000  (close this window to quit)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
