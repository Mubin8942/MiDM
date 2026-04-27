@echo off
TITLE MiDM Setup
color 0B
echo.
echo  ============================================
echo    MiDM - Modern Internet Download Manager
echo    Setup Script
echo  ============================================
echo.

:: Check Python
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Python not found. Install from https://python.org
    pause & exit /b 1
)
echo [OK] Python found

:: Check Node
node --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Node.js not found. Install from https://nodejs.org
    pause & exit /b 1
)
echo [OK] Node.js found

:: Check Rust
rustc --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [WARNING] Rust not found. Install from https://rustup.rs
    echo           Rust is required to build the Tauri .exe
    echo           After installing Rust, re-run this script.
    pause & exit /b 1
)
echo [OK] Rust found

:: Python deps
echo.
echo [1/3] Installing Python backend dependencies...
pip install -r requirements.txt --quiet
IF ERRORLEVEL 1 (echo [ERROR] pip install failed & pause & exit /b 1)
echo [OK] Python packages installed

:: Node deps
echo.
echo [2/3] Installing frontend dependencies...
cd midm-ui
npm install --silent
IF ERRORLEVEL 1 (echo [ERROR] npm install failed & pause & exit /b 1)
cd ..
echo [OK] Node packages installed

echo.
echo [3/3] Setup complete!
echo.
echo  To run MiDM in DEVELOPMENT mode:
echo  ----------------------------------------
echo  Terminal 1:  python backend/server.py
echo  Terminal 2:  cd midm-ui ^&^& npm run tauri dev
echo  ----------------------------------------
echo.
echo  To BUILD the .exe installer:
echo  ----------------------------------------
echo  cd midm-ui ^&^& npm run tauri build
echo  Output: midm-ui/src-tauri/target/release/bundle/
echo  ----------------------------------------
echo.
pause
