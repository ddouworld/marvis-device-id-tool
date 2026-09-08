@echo off
chcp 65001 >nul
setlocal
set "PYTHON_EXE=python"
if exist "C:\Python313\python.exe" set "PYTHON_EXE=C:\Python313\python.exe"
"%PYTHON_EXE%" -B "%~dp0marvis_device_id.py" menu
set "SCRIPT_EXIT_CODE=%ERRORLEVEL%"
if not "%SCRIPT_EXIT_CODE%"=="0" (
  echo.
  echo Script stopped unexpectedly. Check the error above.
  pause
)
exit /b %SCRIPT_EXIT_CODE%
