@echo off
rem Mide toda la sesion (montaje A). Cerrar la app antes: ocupa el puerto.
cd /d "%~dp0"
python medir_todo.py
pause
