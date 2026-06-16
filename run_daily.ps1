# Fetch latest transcripts and push them to the public data repo.
# Scheduled via Task Scheduler with "wake to run", so it may start a few
# seconds before Wi-Fi reconnects after sleep — hence the network waits below.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

# Wait up to ~2 min for the network (Wi-Fi reconnect after wake).
for ($i = 0; $i -lt 24; $i++) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com" -TimeoutSec 5 | Out-Null
        break
    } catch { Start-Sleep -Seconds 5 }
}

& $py fetch_transcripts.py

# Commit + push only if the data actually changed.
git add data/transcripts.json
if (git status --porcelain data/transcripts.json) {
    git commit -m "transcripts: update $(Get-Date -Format yyyy-MM-dd)"
    # Retry the push in case the network is still settling.
    for ($i = 0; $i -lt 5; $i++) {
        git push origin main
        if ($LASTEXITCODE -eq 0) { Write-Host "Pushed updated transcripts."; break }
        Start-Sleep -Seconds 15
    }
} else {
    Write-Host "No transcript changes to push."
}
