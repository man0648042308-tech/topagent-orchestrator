@echo off
setlocal
chcp 65001 > nul

if "%TOPAGENT_PROJECT_DIR%"=="" (
  set "PROJECT_DIR=%USERPROFILE%\AI-Project-TopAgent"
) else (
  set "PROJECT_DIR=%TOPAGENT_PROJECT_DIR%"
)

echo TopAgent v3 setup
if not exist "%PROJECT_DIR%\CLAUDE.md" (
  git clone https://github.com/man0648042308-tech/AI-Project-TopAgent.git "%PROJECT_DIR%"
  if errorlevel 1 exit /b 1
)
cd /d "%PROJECT_DIR%"

where python >nul 2>nul || (echo Python 3 is required & exit /b 1)
where claude >nul 2>nul || npm install -g @anthropic-ai/claude-code

python -m topagent init
if errorlevel 1 exit /b 1

echo No API key is embedded in this installer.
echo Add one without exposing it in command history:
echo   python -m topagent secrets set DASHSCOPE_API_KEY
echo Start dashboard: python -m topagent serve
endlocal
