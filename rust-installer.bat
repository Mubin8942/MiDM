@echo off
TITLE Install Rust for MiDM
color 0D
cls
echo.
echo  ============================================
echo    Installing Rust (required for Tauri)
echo  ============================================
echo.
echo  This will:
echo    1. Download rustup-init.exe (~8 MB)
echo    2. Install Rust + Cargo
echo    3. Install the Tauri CLI
echo.
echo  Estimated time: 5-10 minutes
echo.
pause

:: Download rustup
echo  Downloading rustup installer...
curl -Lo "%TEMP%\rustup-init.exe" "https://win.rustup.rs/x86_64"

if ERRORLEVEL 1 (
    echo [ERROR] Download failed. Check your internet connection.
    pause & exit /b 1
)

:: Run installer
echo.
echo  Running Rust installer...
echo  When asked, press 1 (default install) then Enter.
echo.
"%TEMP%\rustup-init.exe" --default-toolchain stable --profile default -y

if ERRORLEVEL 1 (
    echo [ERROR] Rust installation failed.
    pause & exit /b 1
)

:: Reload PATH
call "%USERPROFILE%\.cargo\env.bat" >nul 2>&1
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

echo.
echo  Verifying Rust install...
rustc --version
cargo --version

echo.
echo  ============================================
echo   Rust installed successfully!
echo  ============================================
echo.
echo  IMPORTANT: Close this window and open a
echo  NEW terminal before running dev.bat
echo  (PATH needs to refresh)
echo.
pause