@echo off
setlocal
cd /d "%~dp0"

echo Instalando dependencias de compilacao...
py -m pip install -r requirements.txt
if errorlevel 1 (
    echo Falha ao instalar dependencias.
    pause
    exit /b 1
)

set "MAPA_APS="
if exist mapa_aps.html set "MAPA_APS=--add-data mapa_aps.html;."

echo Gerando ConsultaImpressoras.exe...
py -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name ConsultaImpressoras ^
    --icon app.ico ^
    --add-data "config.example.json;." ^
    %MAPA_APS% ^
    consulta_impressoras.py
if errorlevel 1 (
    echo Falha ao gerar o executavel.
    pause
    exit /b 1
)

echo.
echo Executavel gerado em: %~dp0dist\ConsultaImpressoras.exe
pause
