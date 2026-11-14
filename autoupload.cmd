@echo off
rem Lance l'auto-upload des replays en arriere-plan (sans fenetre).
rem Journal : data\autoupload.log
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
start "" "%~dp0.venv\Scripts\pythonw.exe" -m rlpi.autoupload %*
