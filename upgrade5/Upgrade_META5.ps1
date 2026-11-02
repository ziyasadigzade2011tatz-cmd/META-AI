param([switch]$Rollback,[string]$Core='D:\META\Core',[string]$Desktop='C:\Users\user\Downloads\META_1_3_Hotfix')
$ErrorActionPreference='Stop'
$python=Join-Path $Core '.venv\Scripts\python.exe'
$installer=Join-Path $PSScriptRoot 'installer.py'
if (!(Test-Path -LiteralPath $python -PathType Leaf)) {throw 'Existing Core virtual environment is required'}
if (!$Rollback) {& $python $installer check --core $Core --desktop $Desktop;if ($LASTEXITCODE -ne 0){throw 'Preflight failed'}}
# Refuse to interrupt an agent that is currently working.
try {
  $cfg=Get-Content -LiteralPath (Join-Path $Core 'meta40_config.json') -Raw | ConvertFrom-Json
  $status=Invoke-RestMethod 'http://127.0.0.1:8000/agent40/status' -Headers @{'X-Meta40-Token'=$cfg.token} -TimeoutSec 3
  if ($status.active){throw 'META has an active task. Stop or finish it first.'}
} catch {if ($_.Exception.Message -like '*active task*'){throw}}
$taskProcesses=Get-CimInstance Win32_Process | Where-Object {($_.Name -match '^pythonw?\.exe$') -and ($_.CommandLine -match 'uvicorn\s+main:app|meta_desktop\.py')}
foreach($item in $taskProcesses){
  $isCore=($item.CommandLine -match 'uvicorn\s+main:app') -and ($item.ExecutablePath -eq $python -or $item.CommandLine.Contains($python))
  $isDesktop=($item.CommandLine -match 'meta_desktop\.py') -and ($item.CommandLine.Contains($Desktop) -or $item.ExecutablePath -eq $python)
  if ($isCore -or $isDesktop){Stop-Process -Id $item.ProcessId -Force -ErrorAction SilentlyContinue}
}
Start-Sleep -Seconds 2
foreach($port in @(8000,8767)){
  if(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue){throw ('Port '+$port+' is still in use. Close META before retrying.')}
}
try {
  if($Rollback){& $python $installer rollback}else{& $python $installer install --core $Core --desktop $Desktop}
  if($LASTEXITCODE -ne 0){throw 'Installation failed; files were restored when possible'}
} finally {
  Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $Core -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'core.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'core.stderr.log')
}
$healthy=$false
for($attempt=0;$attempt -lt 20;$attempt++){
  Start-Sleep -Seconds 1
  try{$h=Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 3;if($h.status -eq 'online'){$healthy=$true;break}}catch{}
}
if(!$healthy){throw 'Core did not become healthy. Use rollback and inspect core.stderr.log.'}
Start-Process -FilePath $python -ArgumentList @((Join-Path $Desktop 'meta_desktop.py')) -WorkingDirectory $Desktop -WindowStyle Normal
Write-Output ('META Core is online: '+$h.version)
