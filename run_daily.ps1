# Fetch latest transcripts and push them to the public data repo.
# Schedule this with Windows Task Scheduler to run each morning (~08:00 IST),
# before the Anthropic-cloud routine runs at 08:30 IST.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Use the project venv if present, else system python.
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

& $py fetch_transcripts.py

# Commit + push only if the data actually changed.
git add data/transcripts.json
if (git status --porcelain data/transcripts.json) {
    git commit -m "transcripts: update $(Get-Date -Format yyyy-MM-dd)"
    git push origin main
    Write-Host "Pushed updated transcripts."
} else {
    Write-Host "No transcript changes to push."
}
