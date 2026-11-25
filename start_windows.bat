@echo off
cd /d "%~dp0"
echo Starting PlaceFlow AI at http://127.0.0.1:8765 ...
start "" http://127.0.0.1:8765
python server.py
pause
