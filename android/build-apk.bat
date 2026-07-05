@echo off
set ANDROID_HOME=C:\Users\39474\AppData\Local\Android\Sdk
set JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-17.0.18.8-hotspot
set GRADLE_OPTS=-Dorg.gradle.jvmargs=-Xmx2048m
set PROJECT_DIR=C:\Users\39474\Desktop\JYD-6-17-2142

cd /d %PROJECT_DIR%

REM Clear config cache
if exist .gradle\configuration-cache rmdir /s /q .gradle\configuration-cache

echo Building debug APK...
echo.

C:\Users\39474\.gradle\wrapper\dists\gradle-8.7-bin\9zpcdmofi6tavecpj4ka1zls7\gradle-8.7\bin\gradle.bat assembleDebug --no-daemon --console=plain

set EXIT_CODE=%ERRORLEVEL%
echo.
if %EXIT_CODE% equ 0 (
    echo BUILD SUCCESS!
) else (
    echo BUILD FAILED with code %EXIT_CODE%
)
exit /b %EXIT_CODE%
