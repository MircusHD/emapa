@echo off

echo ===============================
echo Instalare eMapa Apa Prod
echo ===============================

cd /d F:\doc-mapa-v2

echo.
echo 1. Creare Virtual Environment
python -m venv .venv

echo.
echo 2. Activare venv
call .venv\Scripts\activate

echo.
echo 3. Upgrade pip
python -m pip install --upgrade pip

echo.
echo 4. Instalare librarii
pip install streamlit
pip install sqlalchemy
pip install pandas
pip install bcrypt
pip install pillow
pip install numpy
pip install pypdf
pip install reportlab
pip install streamlit-drawable-canvas
pip install fastapi

echo.
echo ===============================
echo Instalare finalizata
echo ===============================

pause