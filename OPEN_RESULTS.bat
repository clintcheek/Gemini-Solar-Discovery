@echo off
cd /d "%~dp0"
if not exist output mkdir output
if not exist logs mkdir logs
start "" output
start "" logs
