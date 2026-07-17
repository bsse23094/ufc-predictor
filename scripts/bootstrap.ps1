[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

$python = Get-Command py -ErrorAction SilentlyContinue
if ($null -eq $python) {
    throw "Python launcher 'py' is required to bootstrap uv. Install Python 3.11+ or install uv separately."
}

Write-Host "Installing the pinned uv bootstrap tool with the local Python launcher..."
Invoke-Checked "py" @("-3", "-m", "pip", "install", "--user", "uv==0.7.13")
Invoke-Checked "py" @("-3", "-m", "uv", "python", "install", "3.12")
Invoke-Checked "py" @("-3", "-m", "uv", "sync", "--all-packages", "--group", "dev")

if ($null -eq (Get-Command corepack -ErrorAction SilentlyContinue)) {
    throw "Corepack is required for the pinned pnpm workspace. Install a supported Node.js release."
}

Invoke-Checked "corepack" @("enable")
Invoke-Checked "corepack" @("pnpm", "install", "--frozen-lockfile")

Write-Host "Bootstrap complete. Restart the shell if the uv executable is not yet on PATH."
