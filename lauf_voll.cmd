@echo off
rem Automatischer Lauf (Windows-Aufgabenplanung "Aktienresearch voll"). Dieser Rechner ist Laeufer, bis GitHub Actions uebernimmt.
cd /d D:\Energie\AAA_CLAUDE\Aktienresearch
set AKTIEN_LAEUFER=1
set PYTHONIOENCODING=utf-8
echo ===== %date% %time% >> logs\voll.log
.venv\Scripts\python.exe monitor.py --telegram >> logs\voll.log 2>&1
