# Run as the current user. Restart Ollama after existing tasks finish.
$ErrorActionPreference='Stop'
$values=@{OLLAMA_FLASH_ATTENTION='1';OLLAMA_NUM_PARALLEL='1';OLLAMA_MAX_LOADED_MODELS='1'}
foreach($name in $values.Keys){[Environment]::SetEnvironmentVariable($name,$values[$name],'User')}
Write-Output 'Performance settings saved. Restart Ollama after completing current tasks. KV-cache precision was not changed.'
