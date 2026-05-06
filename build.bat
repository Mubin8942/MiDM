@echo off
TITLE MiDM Build
color 0D

echo.
echo  ============================================
echo    MiDM - Building Production .exe
echo  ============================================
echo.

:: ── Step 1: Install Nuitka ───────────────────────────────────────────
echo [1/3] Installing Nuitka...
python.exe -m pip install nuitka ordered-set zstandard --quiet
IF ERRORLEVEL 1 (
    echo [ERROR] Failed to install Nuitka
    pause & exit /b 1
)
echo [OK] Nuitka ready

:: ── Step 2: Compile Python backend ───────────────────────────────────
echo.
echo [2/3] Compiling Python backend with Nuitka...
cd backend

python -m nuitka ^
    --standalone ^
    --onefile ^
    --output-dir=../dist ^
    --output-filename=midm-backend.exe ^
    --windows-disable-console ^
    --include-package=aiohttp ^
    --include-package=aiofiles ^
    --include-package=certifi ^
    --include-package=core ^
    --include-data-dir=core=core ^
    --company-name="MiDM" ^
    --product-name="MiDM Backend" ^
    --file-version=1.0.0.0 ^
    --product-version=1.0.0.0 ^
    server.py

IF ERRORLEVEL 1 (
    echo [ERROR] Nuitka compilation failed
    cd ..
    pause & exit /b 1
)
cd ..
echo [OK] Backend compiled to dist/midm-backend.exe

:: ── Step 3: Copy backend into Tauri resources ─────────────────────────
echo.
echo Copying backend into Tauri resources...
IF NOT EXIST "midm-ui\src-tauri\resources" mkdir "midm-ui\src-tauri\resources"

copy "dist\midm-backend.exe" "midm-ui\src-tauri\midm-backend.exe" /Y
IF ERRORLEVEL 1 (
    echo [ERROR] Failed to copy midm-backend.exe to Tauri resources
    pause & exit /b 1
)
echo [OK] Backend copied to midm-ui\src-tauri

:: ── Step 4: Build Tauri installer ────────────────────────────────────
echo.
echo [3/3] Building Tauri installer...
cd midm-ui
npm run tauri build
IF ERRORLEVEL 1 (
    echo [ERROR] Tauri build failed
    cd ..
    pause & exit /b 1
)
cd ..

:: ── Done ──────────────────────────────────────────────────────────────
echo.
echo  ============================================
echo    Build Complete!
echo  ============================================
echo.
echo  Installer location:
echo  midm-ui\src-tauri\target\release\bundle\nsis\
echo.
pause