# Update META 1.3 in-place, without touching the Core, models, or data.
$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Read-Host 'Full path of existing META_Desktop_1_3 directory'
if (!(Test-Path (Join-Path $target 'meta_desktop.py'))) { throw 'Original META 1.3 not found' }
$backup = Join-Path $target ('backup_before_hotfix_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item (Join-Path $target 'meta_desktop.py') $backup
Copy-Item (Join-Path $target 'assets') (Join-Path $backup 'assets') -Recurse
Copy-Item (Join-Path $source 'meta_desktop.py') (Join-Path $target 'meta_desktop.py') -Force
Copy-Item (Join-Path $source 'assets\app.css') (Join-Path $target 'assets\app.css') -Force
Copy-Item (Join-Path $source 'assets\app.js') (Join-Path $target 'assets\app.js') -Force
Copy-Item (Join-Path $source 'assets\index.html') (Join-Path $target 'assets\index.html') -Force
Write-Host 'Updated META 1.3 in place. Backup:' $backup
Write-Host 'Do not copy a new account database into the existing folder.'
