@echo off
TITLE MiDM Dev
color 0B
cls
echo.
echo  ============================================
echo    MiDM - Modern Internet Download Manager
echo    Development Mode
echo  ============================================
echo.

:: ── Check if we're in the right folder ──────────
if not exist "backend\server.py" (
    echo [ERROR] Run this from the MiDM project root folder.
    echo         Example: cd C:\Projects\MiDM ^&^& dev.bat
    pause & exit /b 1
)

:: ── Check Python ─────────────────────────────────
python --version >nul 2>&1
if ERRORLEVEL 1 (
    echo [ERROR] Python not found. Install from https://python.org
    pause & exit /b 1
)

:: ── Check pip deps installed ──────────────────────
python -c "import aiohttp" >nul 2>&1
if ERRORLEVEL 1 (
    echo [INFO] Installing Python dependencies...
    pip install -r requirements.txt --quiet
)

:: ── Start Python backend in a new window ─────────
echo  [1/2] Starting Python backend...
start "MiDM Backend" cmd /k "color 0A && title MiDM Backend && echo. && echo  MiDM Backend Server && echo  ======================== && echo. && python backend/server.py"

:: ── Wait for backend to be ready ─────────────────
echo  [2/2] Waiting for backend to start...
timeout /t 3 /nobreak >nul

:: ── Check if Rust/Tauri is available ─────────────
rustc --version >nul 2>&1
if ERRORLEVEL 1 (
    goto :no_rust
)

cargo tauri --version >nul 2>&1
if ERRORLEVEL 1 (
    :: Rust exists but tauri-cli not in cargo — try npm tauri
    goto :try_npm_tauri
)

:try_npm_tauri
echo.
echo  Rust found! Launching native desktop app...
echo  (First launch compiles Rust — takes 2-5 minutes)
echo.
cd midm-ui
npm run tauri dev
goto :end

:no_rust
:: ── Rust not installed — open browser instead ────
echo.
echo  ============================================
echo   Rust is NOT installed.
echo   Opening UI in browser instead.
echo  ============================================
echo.
echo  To get the REAL desktop app (.exe window):
echo    1. Run install-rust.bat
echo    2. Restart your terminal
echo    3. Run dev.bat again
echo.
echo  For now, opening http://localhost:5173 in browser...
echo.

:: Start Vite dev server in background
start "MiDM UI (Vite)" cmd /k "color 09 && title MiDM UI && cd midm-ui && npm run dev"

:: Wait for Vite to start
timeout /t 4 /nobreak >nul

:: Open browser
start "" "http://localhost:5173"

echo  Browser opened! MiDM is running at http://localhost:5173
echo.
echo  Press any key to stop all MiDM processes...
pause >nul

:: Kill backend and vite on exit
taskkill /FI "WINDOWTITLE eq MiDM Backend" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq MiDM UI (Vite)" /F >nul 2>&1

:end