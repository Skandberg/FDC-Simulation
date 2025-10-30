@echo off
REM BAT file to install dependencies and launch the FDC GUI project.
REM This installs Kivy (required for fdc_gui.py) and runs the GUI.
REM Assumes Python and pip are installed and in PATH.
REM Place this BAT file in the same directory as fdc_gui.py and fdc_simulator.py.
echo Checking and installing dependencies...
pip install kivy==2.3.1
echo Starting the FDC GUI application...
python fdc_gui.py
pause