@echo off

echo ====================================
echo Instalare eMapa Apa Prod Server
echo ====================================

cd /d F:\doc-mapa-v2

echo.
echo [1] Creare Virtual Environment
python -m venv .venv

echo.
echo [2] Activare venv
call .venv\Scripts\activate

echo.
echo [3] Upgrade pip
python -m pip install --upgrade pip

echo.
echo [4] Instalare librarii
pip install streamlit sqlalchemy pandas bcrypt pillow numpy pypdf reportlab streamlit-drawable-canvas fastapi

echo.
echo [5] Creare foldere daca lipsesc
mkdir data 2>nul
mkdir data\uploads 2>nul
mkdir data\signatures 2>nul
mkdir data\final 2>nul

echo.
echo [6] Deschidere port firewall 2645
netsh advfirewall firewall add rule name="eMapaServer2645" dir=in action=allow protocol=TCP localport=2645

echo.
echo ====================================
echo Pornire server eMapa
echo ====================================

streamlit run app.py ^
--server.address 0.0.0.0 ^
--server.port 2645 ^
--server.headless true ^
--browser.gatherUsageStats false ^
--server.fileWatcherType none

pause