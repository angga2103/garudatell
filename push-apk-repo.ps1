# ========================================================
# Script Otomatis Sync & Push iPay Hybrid APK ke GitHub
# Target: https://github.com/angga2103/ipayHybirdapk.git
# ========================================================

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Sync & Push iPay Hybrid APK to GitHub" -ForegroundColor Green
Write-Host " Target: https://github.com/angga2103/ipayHybirdapk.git" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan

Set-Location -Path $PSScriptRoot

Write-Host "[1/4] Memeriksa perubahan git di mobile-flutter..." -ForegroundColor Cyan
git add mobile-flutter
$gitDiff = git status -s mobile-flutter
if ($gitDiff) {
    Write-Host "Menemukan perubahan di mobile-flutter, melakukan commit..." -ForegroundColor Yellow
    git commit -m "update(mobile-flutter): sync hybrid APK updates"
} else {
    Write-Host "Tidak ada perubahan baru di mobile-flutter yang belum di-commit." -ForegroundColor Gray
}

Write-Host "[2/4] Memperbarui branch hybrid-apk-main..." -ForegroundColor Cyan
git subtree split --prefix=mobile-flutter -b hybrid-apk-main

Write-Host "[3/4] Melakukan push branch main ke GitHub (ipay-apk)..." -ForegroundColor Cyan
git push ipay-apk hybrid-apk-main:main --force

Write-Host "[4/4] Memperbarui Release Tag v1.0.5 ke GitHub (ipay-apk)..." -ForegroundColor Cyan
git tag -f v1.0.5 hybrid-apk-main
git push ipay-apk v1.0.5 --force

Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host " Sukses! GitHub Actions akan otomatis membuild APK rilis." -ForegroundColor Green
Write-Host " Halaman Rilis: https://github.com/angga2103/ipayHybirdapk/releases" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Green
