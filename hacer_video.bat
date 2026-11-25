@echo off
rem ============================================================
rem  Generador de videos verticales
rem  Arrastra un audio (mp3, m4a, wav, ogg) o una grabacion de OBS
rem  (mkv, mp4, mov) encima de este archivo.
rem  Audio  -> plantilla "animado"   (escenario de papel)
rem  Video  -> modo OBS, plantilla "juego"
rem  Para cambiar la plantilla, edita las dos lineas "set PLANTILLA".
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

if "%~1"=="" (
    echo Arrastra un audio o una grabacion de OBS encima de este archivo.
    set /p "ENTRADA=O escribe la ruta aqui: "
) else (
    set "ENTRADA=%~1"
)
for %%F in ("%ENTRADA%") do set "EXT=%%~xF"

set "MODO=normal"
set "PLANTILLA=animado"
for %%E in (.mkv .mp4 .mov .flv) do if /i "%EXT%"=="%%E" (
    set "MODO=obs"
    set "PLANTILLA=juego"
)

echo.
echo Entrada:   %ENTRADA%
echo Modo:      %MODO%   Plantilla: %PLANTILLA%
echo.
".venv\Scripts\python.exe" hacer_video.py --modo %MODO% --entrada "%ENTRADA%" --plantilla %PLANTILLA%
echo.
echo Los videos quedan en la carpeta "salida".
pause
