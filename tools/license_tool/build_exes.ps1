# Build two small EXEs (no omni-bot-sdk dependency)
# powershell -ExecutionPolicy Bypass -File tools/license_tool/build_exes.ps1

$ErrorActionPreference = "Stop"
$ToolDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ToolDir "..\..")
$Dist = Join-Path $ToolDir "dist"
$Work = Join-Path $ToolDir "build_pyi"

Set-Location $ToolDir
Write-Host "ToolDir: $ToolDir"

python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PyInstaller..."
    python -m pip install -U pyinstaller
}

if (Test-Path $Dist) {
    Get-ChildItem $Dist -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
if (Test-Path $Work) { Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $Dist | Out-Null

Write-Host ""
Write-Host "=== Building show-machine-code.exe ==="
python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --paths $ToolDir `
    --distpath $Dist `
    --workpath $Work `
    --specpath $Work `
    --name "show-machine-code" `
    --hidden-import "machineid" `
    --hidden-import "machine_util" `
    (Join-Path $ToolDir "show_machine_code_gui.py")
if ($LASTEXITCODE -ne 0) { throw "build show-machine-code failed" }

Write-Host ""
Write-Host "=== Building issue-license.exe ==="
python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --paths $ToolDir `
    --distpath $Dist `
    --workpath $Work `
    --specpath $Work `
    --name "issue-license" `
    --hidden-import "cryptography" `
    --hidden-import "machine_util" `
    --hidden-import "issue_license" `
    (Join-Path $ToolDir "issue_license_gui.py")
if ($LASTEXITCODE -ne 0) { throw "build issue-license failed" }

$Priv = Join-Path $ToolDir "private_key.pem"
if (Test-Path $Priv) {
    Copy-Item $Priv (Join-Path $Dist "private_key.pem") -Force
    Write-Host "Copied private_key.pem into dist"
} else {
    Write-Host "WARN: private_key.pem missing"
}

# Optional Chinese names via cmd (UTF-8)
$Utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText(
    (Join-Path $Dist "_rename.bat"),
    "@echo off`r`nchcp 65001 >nul`r`ncopy /Y `"show-machine-code.exe`" `"查看机器码.exe`" >nul`r`ncopy /Y `"issue-license.exe`" `"生成激活码.exe`" >nul`r`n",
    $Utf8
)
Push-Location $Dist
cmd /c "_rename.bat"
Remove-Item "_rename.bat" -Force
Pop-Location

Write-Host ""
Write-Host "Done: $Dist"
Get-ChildItem $Dist | Format-Table Name, Length
