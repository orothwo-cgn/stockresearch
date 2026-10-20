@echo off
rem Automatischer Lauf (Windows-Aufgabenplanung "Aktienresearch schnell"). Dieser Rechner ist Laeufer, bis GitHub Actions uebernimmt.
cd /d D:\Energie\AAA_CLAUDE\Aktienresearch
set AKTIEN_LAEUFER=1
set PYTHONIOENCODING=utf-8
echo ===== %date% %time% >> logs\schnell.log
.venv\Scripts\python.exe monitor.py --schnell --telegram >> logs\schnell.log 2>&1
