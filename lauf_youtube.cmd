@echo off
rem Automatischer Lauf (Windows-Aufgabenplanung "Aktienresearch youtube"): neue Videos und Transkripte holen.
cd /d D:\Energie\AAA_CLAUDE\Aktienresearch
set PYTHONIOENCODING=utf-8
echo ===== %date% %time% >> logs\youtube.log
.venv\Scripts\python.exe youtube.py >> logs\youtube.log 2>&1
