@echo off
REM Run a local shell script on the target host via ssh, with LF endings
REM and no BOM. Usage: remote-run.cmd <script-path> [ssh-host-alias]
REM
REM Configuration is read from untracked, machine-specific files:
REM   ssh_config.local  - real host/IP (falls back to ssh_config placeholder)
REM   askpass.secret    - the SSH password (falls back to askpass.cmd)
REM Both are gitignored; no credentials live in this repository.
setlocal enabledelayedexpansion
set "HERE=%~dp0"
set "SCRIPT=%~1"
set "HOST=%~2"
if "!HOST!"=="" set "HOST=opencode-target"

set "CFG=!HERE!ssh_config.local"
if not exist "!CFG!" set "CFG=!HERE!ssh_config"

REM SSH_ASKPASS needs an executable that prints the password on stdout.
REM NOTE: variables set inside an if-block must be read with !..!, because
REM %..% is expanded once at parse time (before the block runs).
set "OWNASKPASS="
if exist "!HERE!askpass.secret" (
    set "TMPASK=!TEMP!\oc-askpass-!RANDOM!.cmd"
    > "!TMPASK!" echo @echo off
    >> "!TMPASK!" echo set /p OC_PW=^<"!HERE!askpass.secret"
    >> "!TMPASK!" echo echo %%OC_PW%%
    set "OWNASKPASS=!TMPASK!"
) else (
    set "TMPASK=!HERE!askpass.cmd"
)
if not exist "!TMPASK!" (
    echo error: provide !HERE!askpass.secret ^(gitignored^) or !HERE!askpass.cmd 1>&2
    exit /b 1
)
set "SSH_ASKPASS=!TMPASK!"
set "SSH_ASKPASS_REQUIRE=force"
set "DISPLAY=localhost:0"

REM Normalize to LF and strip BOM; ssh needs LF line endings and no CR.
set "TMPLF=!TEMP!\oc-run-!RANDOM!.sh"
powershell -NoProfile -Command "$b=[IO.File]::ReadAllBytes('!SCRIPT!'); if($b.Length -ge 3 -and $b[0] -eq 239 -and $b[1] -eq 187 -and $b[2] -eq 191){$b=$b[3..($b.Length-1)]}; $t=[Text.Encoding]::UTF8.GetString($b) -replace \"`r`n\", \"`n\" -replace \"`r\", \"`n\"; [IO.File]::WriteAllText('!TMPLF!', $t, (New-Object Text.UTF8Encoding($false)))"

ssh -F "!CFG!" "!HOST!" "bash -s" < "!TMPLF!"
set "RC=!ERRORLEVEL!"
del "!TMPLF!" >nul 2>&1
if defined OWNASKPASS del "!OWNASKPASS!" >nul 2>&1
endlocal & exit /b %RC%
