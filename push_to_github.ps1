# GitHub Yukleyici - MTK BROM Dumper & Forensic Extractor
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  GITHUB REPO YUKLEYICI" -ForegroundColor Cyan
Write-Host "  Hedef: https://github.com/starqus/MTK-BRom-Dumper-Buckup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Set-Location -Path "F:\CHATGPT\MTK6582v\github"

if (-not (Test-Path ".git")) {
    Write-Host "[*] Git deposu baslatiliyor..." -ForegroundColor Yellow
    git init
    git branch -M main
}

Write-Host "[*] Uzak repo adresi baglaniyor..." -ForegroundColor Yellow
git remote remove origin 2>$null
git remote add origin https://github.com/starqus/MTK-BRom-Dumper-Buckup.git

Write-Host "[*] Dosyalar hazirlaniyor (git add)..." -ForegroundColor Yellow
git add .

Write-Host "[*] Ilk commit olusturuluyor..." -ForegroundColor Yellow
git commit -m "Initial commit: MediaTek BROM Dumper & Forensic Extractor"

Write-Host "`n[*] GitHub'a gonderiliyor (git push)..." -ForegroundColor Yellow
Write-Host "[i] Tarayicinizda GitHub oturum onay penceresi acilirsa giris yapin...`n" -ForegroundColor Gray

git push -u origin main --force

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n============================================================" -ForegroundColor Green
    Write-Host "[OK] TEBRIKLER! PROJE BASARIYLA GITHUB'A YUKLENDI!" -ForegroundColor Green
    Write-Host "Repo: https://github.com/starqus/MTK-BRom-Dumper-Buckup" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
} else {
    Write-Host "`n[!] Yukleme sirasinda hata olustu. GitHub kimlik dogrulamanizi kontrol edin." -ForegroundColor Red
}
