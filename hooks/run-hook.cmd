@echo off
setlocal enabledelayedexpansion

:: run-hook.cmd — Windows polyglot wrapper for fangcun hooks
:: Searches for Git Bash, then executes the named hook script.

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_NAME=%~1"

if "%SCRIPT_NAME%"=="" (
    echo Usage: run-hook.cmd ^<hook-name^>
    exit /b 1
)

set "BASH="

:: Search for Git Bash in standard locations
for %%D in (
    "C:\Program Files\Git\bin\bash.exe"
    "C:\Program Files (x86)\Git\bin\bash.exe"
) do (
    if exist %%D (
        set "BASH=%%~D"
        goto :found
    )
)

:: Fall back to PATH
for %%C in (bash.exe) do set "BASH=%%~$PATH:C"
if not "%BASH%"=="" goto :found

echo ERROR: Git Bash not found. Install Git for Windows.
exit /b 1

:found
"%BASH%" "%SCRIPT_DIR%%SCRIPT_NAME%"
exit /b %ERRORLEVEL%
