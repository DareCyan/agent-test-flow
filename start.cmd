@echo off
REM ============================================================
REM  Agent Test Workbench - start backend + frontend
REM  Page:  http://127.0.0.1:8787/
REM  Needs: Python 3.10+  (standard library only, no pip install)
REM
REM  NOTE: keep this file CRLF-encoded and ASCII-only.
REM        cmd.exe mis-parses LF-only .cmd files (it eats the
REM        leading word of a line inside (...) blocks), and a
REM        UTF-8 CJK echo garbles in a non-UTF8 console.
REM ============================================================
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto NOPYTHON

if exist "backend\config.yaml" goto HAVECFG
if exist "backend\config.yml" goto HAVECFG
if exist "backend\config.json" goto HAVECFG
echo [INFO] No backend\config.yaml / config.yml / config.json - step1 uses mock data.
goto RUN

:HAVECFG
echo [INFO] Found backend\config.* - step1 will call the configured LLM.
goto RUN

:NOPYTHON
echo [ERROR] python not found in PATH. Install Python 3.10+ first.
pause
exit /b 1

:RUN
REM -u: unbuffered stdout, so the startup banner shows up even when piped to a log
python -u backend\server.py --port 8787
if errorlevel 1 goto FAILED
goto END

:FAILED
echo [ERROR] Server exited abnormally. Check the message above.
pause

:END
endlocal
