@echo off
TITLE MiDM Build
color 0D
echo.
echo  ============================================
echo    MiDM - Building Production .exe
echo  ============================================
echo.

:: Package Python backend into a single .exe using PyInstaller
echo [1/2] Packaging Python backend with PyInstaller...
pip install pyinstaller --quiet
pyinstaller --onefile --noconsole --name midm-backend ^
    --add-data "backend/core;core" ^
    backend/server.py

IF ERRORLEVEL 1 (
    echo [ERROR] PyInstaller failed
    pause & exit /b 1
)
echo [OK] Backend packaged to dist/midm-backend.exe

:: Copy backend exe into Tauri resources
echo.
echo Copying backend into Tauri resources...
IF NOT EXIST "midm-ui\src-tauri\resources" mkdir "midm-ui\src-tauri\resources"
copy "dist\midm-backend.exe" "midm-ui\src-tauri\resources\" /Y

:: Build Tauri .exe
echo.
echo [2/2] Building Tauri installer...
cd midm-ui
npm run tauri build

echo.
echo  Build complete!
echo  Installer: midm-ui\src-tauri\target\release\bundle\nsis\
echo.
pause
