@echo off

echo ================================
echo UPDATE APLICATIE EMAPA
echo ================================

cd /d F:\doc-mapa

echo.
echo [1] Creare backup baza de date

set dt=%date:~-4%%date:~3,2%%date:~0,2%_%time:~0,2%%time:~3,2%

mkdir backup 2>nul

copy data\app.db backup\app_%dt%.db

echo Backup DB creat.

echo.
echo [2] Backup aplicatie

xcopy app.py backup\app_%dt%.py /Y

echo.
echo [3] Oprire aplicatie

taskkill /F /IM python.exe >nul 2>nul

echo.
echo [4] Aplicare update

copy update\app.py app.py /Y

echo Update aplicat.

echo.
echo [5] Pornire aplicatie

call .venv\Scripts\activate

start cmd /k streamlit run app.py ^
--server.address 192.168.5.111 ^
--server.port 2645 ^
--server.headless true

echo.
echo ================================
echo UPDATE FINALIZAT
echo ================================

pause