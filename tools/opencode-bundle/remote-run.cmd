@echo off
REM Run a local shell script on the target host via ssh, with LF endings
REM and no BOM. Usage: remote-run.cmd <script-path> [ssh-host-alias]
setlocal enabledelayedexpansion
set "SCRIPT=%~1"
set "HOST=%~2"
if "%HOST%"=="" set "HOST=opencode-target"
set "ASKPASS=%~dp0askpass.cmd"
set "SSH_ASKPASS=%ASKPASS%"
set "SSH_ASKPASS_REQUIRE=force"
set "DISPLAY=localhost:0"

REM Normalize to LF and strip BOM; ssh needs LF line endings and no CR.
set "TMPLF=%TEMP%\oc-run-%RANDOM%.sh"
powershell -NoProfile -Command "$b=[IO.File]::ReadAllBytes('%SCRIPT%'); if($b.Length -ge 3 -and $b[0] -eq 239 -and $b[1] -eq 187 -and $b[2] -eq 191){$b=$b[3..($b.Length-1)]}; $t=[Text.Encoding]::UTF8.GetString($b) -replace \"`r`n\", \"`n\" -replace \"`r\", \"`n\"; [IO.File]::WriteAllText('%TMPLF%', $t, (New-Object Text.UTF8Encoding($false)))"

ssh -F "%~dp0ssh_config" "%HOST%" "bash -s" < "%TMPLF%"
set "RC=%ERRORLEVEL%"
del "%TMPLF%" >nul 2>&1
endlocal & exit /b %RC%
