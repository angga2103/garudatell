@echo off
echo ========================================================
echo  Sync & Push iPay Hybrid APK to GitHub
echo  Target: https://github.com/angga2103/ipayHybirdapk.git
echo ========================================================

cd /d "%~dp0"

echo [1/4] Memeriksa perubahan git...
git add mobile-flutter
git diff-index --quiet HEAD -- mobile-flutter
if %errorlevel% neq 0 (
    echo Menemukan perubahan di mobile-flutter, melakukan commit...
    git commit -m "update(mobile-flutter): sync hybrid APK updates"
) else (
    echo Tidak ada perubahan baru yang belum di-commit.
)

echo [2/4] Memperbarui branch hybrid-apk-main...
git subtree split --prefix=mobile-flutter -b hybrid-apk-main

echo [3/4] Melakukan push branch main ke GitHub...
git push ipay-apk hybrid-apk-main:main --force

echo [4/4] Memperbarui Release Tag v1.0.4 di GitHub...
git tag -f v1.0.4 hybrid-apk-main
git push ipay-apk v1.0.4 --force

echo.
echo ========================================================
echo  Berhasil di-push ke GitHub!
echo  Halaman Rilis: https://github.com/angga2103/ipayHybirdapk/releases
echo ========================================================
pause
