$ErrorActionPreference = 'Stop'
$ComposeDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Set-Location $ComposeDir

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm')] Pulling external images..."
docker compose pull portainer cloudflared

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm')] Restarting updated containers..."
docker compose up -d portainer cloudflared

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm')] Done."
