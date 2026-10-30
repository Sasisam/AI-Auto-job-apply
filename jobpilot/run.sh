#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: installing JobPilot, this takes a few minutes..."
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
  playwright install chromium
  cp requirements.txt .venv/req.stamp
else
  . .venv/bin/activate
  cmp -s requirements.txt .venv/req.stamp || { pip install -r requirements.txt && cp requirements.txt .venv/req.stamp; }
fi
[ -f .env ] || cp .env.example .env
echo "JobPilot is running at http://127.0.0.1:8000  (Ctrl+C to quit)"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
