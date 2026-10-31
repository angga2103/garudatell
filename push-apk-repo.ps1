# ========================================================
# Script Otomatis Sync & Push iPay Hybrid APK ke GitHub
# Target: https://github.com/angga2103/ipayHybirdapk.git
# ========================================================

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Sync & Push iPay Hybrid APK to GitHub" -ForegroundColor Green
Write-Host " Target: https://github.com/angga2103/ipayHybirdapk.git" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan

Set-Location -Path $PSScriptRoot

Write-Host "[1/3] Memeriksa perubahan git di mobile-flutter..." -ForegroundColor Cyan
git add mobile-flutter
$gitDiff = git status -s mobile-flutter
if ($gitDiff) {
    Write-Host "Menemukan perubahan di mobile-flutter, melakukan commit..." -ForegroundColor Yellow
    git commit -m "update(mobile-flutter): sync hybrid APK updates"
} else {
    Write-Host "Tidak ada perubahan baru di mobile-flutter yang belum di-commit." -ForegroundColor Gray
}

Write-Host "[2/3] Memperbarui branch hybrid-apk-main..." -ForegroundColor Cyan
git subtree split --prefix=mobile-flutter -b hybrid-apk-main

Write-Host "[3/3] Melakukan push ke GitHub (ipay-apk)..." -ForegroundColor Cyan
git push ipay-apk hybrid-apk-main:main --force

Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host " Sukses! Kode terbaru sudah ter-push ke GitHub:" -ForegroundColor Green
Write-Host " https://github.com/angga2103/ipayHybirdapk.git" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Green
