@echo off
echo ========================================================
echo  Sync & Push iPay Hybrid APK to GitHub
echo  Target: https://github.com/angga2103/ipayHybirdapk.git
echo ========================================================

cd /d "%~dp0"

echo [1/3] Memeriksa perubahan git...
git add mobile-flutter
git diff-index --quiet HEAD -- mobile-flutter
if %errorlevel% neq 0 (
    echo Menemukan perubahan di mobile-flutter, melakukan commit...
    git commit -m "update(mobile-flutter): sync hybrid APK updates"
) else (
    echo Tidak ada perubahan baru yang belum di-commit.
)

echo [2/3] Memperbarui branch hybrid-apk-main...
git subtree split --prefix=mobile-flutter -b hybrid-apk-main

echo [3/3] Melakukan push ke https://github.com/angga2103/ipayHybirdapk.git...
git push ipay-apk hybrid-apk-main:main --force

echo.
echo ========================================================
echo  Berhasil di-push ke https://github.com/angga2103/ipayHybirdapk.git!
echo ========================================================
pause
