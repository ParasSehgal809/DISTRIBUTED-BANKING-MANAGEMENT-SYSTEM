#!/bin/bash
# Distributed Banking Management System - Launcher for macOS / Linux

echo "=========================================================="
echo "    Distributed Banking Management System (ADBMS Project)  "
echo "=========================================================="

# Change to script directory
cd "$(dirname "$0")"

# Check if virtualenv exists, if not create one
if [ ! -d "venv" ]; then
    echo "[+] Creating virtual environment..."
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt
fi

echo "[+] Activating virtual environment..."
source venv/bin/activate

echo "[+] Starting Distributed Banking Server..."
echo "[+] Central Coordinator & 3 Branch Databases Initializing..."
echo "[+] Web Dashboard running at: http://127.0.0.1:5050"
echo "=========================================================="

python3 app.py
