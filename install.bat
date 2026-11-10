@echo off
setlocal EnableExtensions
set "SB_SOURCE=%~dp0"
set "SB_DEST=%LOCALAPPDATA%\Programs\SimpleBuild"
if not exist "%SB_SOURCE%builder.py" (
  echo ERROR: builder.py not found next to install.bat
  pause
  exit /b 1
)
set "SB_PYTHON="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
  if not errorlevel 1 set "SB_PYTHON=py -3"
)
if not defined SB_PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
    if not errorlevel 1 set "SB_PYTHON=python"
  )
)
if not defined SB_PYTHON (
  echo ERROR: Python 3.9+ is required. Install Python and rerun install.bat.
  pause
  exit /b 1
)
if not exist "%SB_DEST%" mkdir "%SB_DEST%" || goto :failed
copy /Y "%SB_SOURCE%builder.py" "%SB_DEST%\builder.py" >nul || goto :failed
> "%SB_DEST%\simple-build.cmd" echo @echo off
>> "%SB_DEST%\simple-build.cmd" echo %SB_PYTHON% "%%~dp0builder.py" %%*
set "SB_PATH=%SB_DEST%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $p=$env:SB_PATH; $old=[Environment]::GetEnvironmentVariable('Path','User'); $parts=@($old -split ';' | Where-Object { $_ }); if (-not ($parts | Where-Object { $_.TrimEnd('\') -ieq $p.TrimEnd('\') })) { [Environment]::SetEnvironmentVariable('Path', (($parts + $p) -join ';'), 'User') }"
if errorlevel 1 goto :failed
echo.
echo Simple Build installed successfully!
echo Open a NEW CMD window and use:
echo   simple-build start
 echo   simple-build cache
 echo   simple-build clear
 echo.
pause
exit /b 0
:failed
echo ERROR: Installation failed.
pause
exit /b 1
