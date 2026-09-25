@echo off
setlocal
cd /d "%~dp0"

if not exist "input\" mkdir "input"
dir /b /a-d "input\*.xlsx" >nul 2>&1
if errorlevel 1 (
    echo No XLSX workbooks found in input.
    echo Copy one or more XLSX files into the input folder and run again.
    pause
    exit /b 1
)

set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    where python >nul 2>&1 && set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo Python 3 was not found.
    echo Install Python 3.12 or newer and enable the Add Python to PATH option.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating a local Python environment...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :error

    echo Installing required packages...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

echo Starting the analysis...
".venv\Scripts\python.exe" fond_analysis.py
if errorlevel 1 goto :error

echo.
echo Analysis completed successfully.
pause
exit /b 0

:error
echo.
echo The script stopped with an error. Review the message above.
pause
exit /b 1
