@echo off
REM Non-interactive SSH password helper for OpenSSH's SSH_ASKPASS mechanism.
REM
REM The password is NOT stored in this file. Put it in an untracked file:
REM     tools\opencode-bundle\askpass.secret   (gitignored)
REM containing just the password on its own line.
REM
REM Usage:  askpass-ssh.cmd <user@host> <port> "<remote command>"
setlocal enabledelayedexpansion

set "HERE=%~dp0"
set "SECRET=!HERE!askpass.secret"

if not exist "!SECRET!" (
    echo error: missing !SECRET! 1>&2
    echo        create it with your SSH password ^(it is gitignored^). 1>&2
    exit /b 1
)

REM SSH_ASKPASS must point at an executable that prints the password.
REM NOTE: !..! is required for variables set inside the block above.
set "TMPASK=!TEMP!\oc-askpass-!RANDOM!.cmd"
> "!TMPASK!" echo @echo off
>> "!TMPASK!" echo set /p OC_PW=^<"!SECRET!"
>> "!TMPASK!" echo echo %%OC_PW%%
set "SSH_ASKPASS=!TMPASK!"
set "SSH_ASKPASS_REQUIRE=force"
set "DISPLAY=localhost:0"

ssh -F "!HERE!ssh_config" -p %2 %1 %~3
set "RC=!ERRORLEVEL!"
del "!TMPASK!" >nul 2>&1
endlocal & exit /b %RC%
