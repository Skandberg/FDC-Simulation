@echo off
REM BAT file to install Python if missing, then dependencies and launch FDC GUI.
REM Requires admin rights for Python install. Place in same dir as fdc_gui.py.

echo Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Installing Python 3.12.7...
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '%TEMP%\python-installer.exe'"
    %TEMP%\python-installer.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
    del %TEMP%\python-installer.exe
    echo Python installed. Restarting shell to update PATH...
    powershell -Command "Start-Sleep -Seconds 5; & '%~dp0%~nx0' %*"
    exit /b
)

echo Checking pip...
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo pip not recognized. Reinstall Python or add to PATH.
    pause
    exit /b 1
)

echo Checking Kivy...
pip show kivy >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing Kivy==2.3.1...
    pip install kivy==2.3.1
    if %errorlevel% neq 0 (
        echo Kivy installation failed.
        pause
        exit /b 1
    )
) else (
    echo Kivy already installed.
)

echo Starting the FDC GUI application...
python fdc_gui.py
if %errorlevel% neq 0 (
    echo GUI launch failed. Check fdc_gui.py exists.
)
pause