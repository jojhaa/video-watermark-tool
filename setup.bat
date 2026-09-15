@echo off
cd /d "%~dp0"
python batch_watermark.py
if errorlevel 1 pause
