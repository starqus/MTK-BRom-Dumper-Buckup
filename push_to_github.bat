@echo off
chcp 65001 >nul
title GitHub Yukleyici - MTK BROM Dumper & Forensic Extractor

echo ============================================================
echo   GITHUB REPO YUKLEYICI
echo   Hedef: https://github.com/starqus/MTK-BRom-Dumper-Buckup
echo ============================================================
echo.

cd /d "F:\CHATGPT\MTK6582v\github"

if not exist ".git" (
    echo [*] Git deposu baslatiliyor...
    git init
    git branch -M main
)

echo [*] Uzak repo adresi yapilandiriliyor...
git remote remove origin 2>nul
git remote add origin https://github.com/starqus/MTK-BRom-Dumper-Buckup.git

echo [*] Dosyalar hazirlaniyor (git add)...
git add .

echo [*] Degisiklikler kaydediliyor (git commit)...
git commit -m "Initial commit: MediaTek BROM Dumper & Forensic Extractor"

echo.
echo [*] GitHub'a yukleniyor (git push)...
echo [i] Eger GitHub giris penceresi acilirsa tarayicidan onay verin...
echo.

git push -u origin main --force

echo.
if %errorlevel% equ 0 (
    echo ============================================================
    echo [OK] BASARIYLA YUKLENDI!
    echo Repo Adresiniz: https://github.com/starqus/MTK-BRom-Dumper-Buckup
    echo ============================================================
) else (
    echo [!] Yukleme sirasinda bir sorun olustu.
    echo [i] Lutfen GitHub kullanici girisinizin yapili oldugundan emin olun.
)

echo.
pause
