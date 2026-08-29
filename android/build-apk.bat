@echo off
setlocal
set GRADLE_OPTS=-Dorg.gradle.jvmargs=-Xmx2048m
set "PROJECT_DIR=%~dp0"

cd /d "%PROJECT_DIR%"
if errorlevel 1 exit /b 1

if not defined JAVA_HOME (
    echo JAVA_HOME must point to a JDK 17 installation.
    exit /b 2
)

if not defined ANDROID_HOME if not defined ANDROID_SDK_ROOT (
    echo Set ANDROID_HOME or ANDROID_SDK_ROOT to the Android SDK directory.
    exit /b 2
)

REM Clear config cache
if exist .gradle\configuration-cache rmdir /s /q .gradle\configuration-cache

echo Building debug APK...
echo.

call "%PROJECT_DIR%gradlew.bat" assembleDebug --no-daemon --console=plain

set EXIT_CODE=%ERRORLEVEL%
echo.
if %EXIT_CODE% equ 0 (
    echo BUILD SUCCESS!
) else (
    echo BUILD FAILED with code %EXIT_CODE%
)
exit /b %EXIT_CODE%
