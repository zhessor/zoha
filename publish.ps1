# Publish Zoha with a single clean commit (no old history).
# Run from this folder in PowerShell: .\publish.ps1
$ErrorActionPreference = "Stop"
if (Test-Path .git) { Remove-Item -Recurse -Force .git }
git init -b main
git add -A
git commit -m "Zoha 0.1.0: voice-first assistant that asks before acting"
git remote add origin https://github.com/zhessor/zoha.git
git push -f -u origin main
