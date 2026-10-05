@echo off
rem ---------------------------------------------------------------------------
rem  Memory Supervisor - launcher
rem
rem  Finds a suitable Python interpreter (preferring pythonw.exe so no console
rem  window flashes up) and starts the panel.  The interpreter search order is:
rem     1. a "runtime" folder next to this script (a copied portable Python)
rem     2. the interpreter recorded in launcher.ini
rem     3. pythonw.exe / python.exe on PATH
rem     4. the py launcher (pyw.exe / py.exe)
rem ---------------------------------------------------------------------------
setlocal EnableExtensions EnableDelayedExpansion
set "PROJECT=%~dp0"
set "SCRIPT=%PROJECT%memsup.py"
set "PY="

rem --- 1. bundled/portable runtime ------------------------------------------
if exist "%PROJECT%runtime\pythonw.exe" (
    set "PY=%PROJECT%runtime\pythonw.exe"
    goto :launch
)
if exist "%PROJECT%runtime\python.exe" (
    set "PY=%PROJECT%runtime\python.exe"
    goto :launch
)

rem --- 2. interpreter recorded in launcher.ini ------------------------------
if exist "%PROJECT%launcher.ini" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%PROJECT%launcher.ini") do (
        if /i "%%A"=="python" if exist "%%B" set "PY=%%B"
    )
    if defined PY goto :launch
)

rem --- 3. PATH ---------------------------------------------------------------
for %%P in (pythonw.exe) do if not defined PY set "PY=%~$PATH:%%P"
for %%P in (python.exe)  do if not defined PY set "PY=%~$PATH:%%P"
if defined PY goto :launch

rem --- 4. py launcher --------------------------------------------------------
for %%P in (pyw.exe) do if not defined PY set "PY=%~$PATH:%%P"
if defined PY (
    set "PYARGS=-3"
    goto :launch
)
for %%P in (py.exe) do if not defined PY set "PY=%~$PATH:%%P"
if defined PY (
    set "PYARGS=-3"
    goto :launch
)

echo.
echo   Memory Supervisor could not find a Python interpreter.
echo.
echo   Install Python 3.8+ from https://www.python.org/downloads/windows/
echo   (tick "Add python.exe to PATH"), then run this file again.
echo.
echo   Alternatively place a portable Python in:  %PROJECT%runtime\
echo.
pause
exit /b 1

:launch
if /I "%PY%"=="%PROJECT%runtime\python.exe" (
    rem python.exe would open a console; there is nothing to do about that
    rem unless pythonw.exe is present.
    echo Starting Memory Supervisor (console visible - add pythonw.exe to the
    echo runtime folder to hide it^)...
)
start "" "%PY%" %PYARGS% "%SCRIPT%" %*
exit /b 0
