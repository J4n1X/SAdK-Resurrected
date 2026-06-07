@echo off
REM SADK Batch Decryption Script
REM Decrypts all .KEX files from Die Siedler and preserves folder structure

setlocal enabledelayedexpansion

REM EDIT PER MACHINE: point SOURCE_DIR at your game's data folder (the dir containing the .KEX files).
set "SOURCE_DIR=<PATH TO YOUR GAME>\data"
set "RESULT_DIR=%~dp0result"
set "ADKED_PATH=%~dp0AdKEd.exe"

REM Create result directory
if not exist "%RESULT_DIR%" mkdir "%RESULT_DIR%"

echo Scanning for .KEX files...
setlocal enabledelayedexpansion

REM Count files first
for /r "%SOURCE_DIR%" %%F in (*.KEX) do (
    set /a TOTAL_FILES+=1
)

echo Found !TOTAL_FILES! .KEX files to decrypt

set "COUNT=0"

for /r "%SOURCE_DIR%" %%F in (*.KEX) do (
    set /a COUNT+=1

    REM Get relative path
    set "FULL_PATH=%%F"
    set "REL_PATH=!FULL_PATH:%SOURCE_DIR%=!"
    set "REL_PATH=!REL_PATH:~1!"

    set "DEST_PATH=%RESULT_DIR%\!REL_PATH!"

    REM Create directory structure
    for %%D in ("!DEST_PATH!") do set "DEST_DIR=%%~dpD"
    if not exist "!DEST_DIR!" mkdir "!DEST_DIR!"

    echo [!COUNT!/!TOTAL_FILES!] Decrypting: !REL_PATH!

    REM Create temp file path
    set "TEMP_FILE=%TEMP%\temp_!RANDOM!_!RANDOM!.KEX"

    REM Copy and decrypt
    copy "%%F" "!TEMP_FILE!" >nul
    "!ADKED_PATH!" "!TEMP_FILE!" >nul 2>&1
    move /y "!TEMP_FILE!" "!DEST_PATH!" >nul
)

echo.
echo Decryption complete! !COUNT! files processed.
echo Results stored in: %RESULT_DIR%
pause
