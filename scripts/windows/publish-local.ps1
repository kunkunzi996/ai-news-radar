# Publish ai-news-radar-run\data to the local site via its ingest endpoint (server checks kept).
$ErrorActionPreference = 'Stop'
$Root = if ($env:RADAR_ROOT) { $env:RADAR_ROOT } else { 'C:\AI-news-reader\ai-news-radar-run' }
$Log = Join-Path $Root 'logs\home-collect.log'
function Write-Log([string]$Message) {
  $line = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' ' + $Message
  Add-Content -Path $Log -Value $line -Encoding utf8
}
$python = Join-Path $Root '.venv\Scripts\python.exe'
$serve = 'C:\AI-news-reader\radar-serve\serve_snapshot.py'
$oldSnap = $env:RADAR_SNAPSHOT_DIR; $oldHttp = $env:HTTP_PROXY; $oldHttps = $env:HTTPS_PROXY; $oldAll = $env:ALL_PROXY; $oldNo = $env:NO_PROXY
try {
  $env:RADAR_SNAPSHOT_DIR = Join-Path $Root 'data'
  $env:HTTP_PROXY = $null; $env:HTTPS_PROXY = $null; $env:ALL_PROXY = $null
  $env:NO_PROXY = '127.0.0.1,localhost,::1'
  Write-Log 'publish start'
  $ErrorActionPreference = 'Continue'
  $out = & $python $serve '--post' 'http://127.0.0.1:8080/api/radar-ingest' 2>&1
  $code = $LASTEXITCODE
  foreach ($l in $out) { Write-Log ('publish ' + [string]$l) }
  Write-Log "publish exit=$code"
  exit $code
} finally {
  $env:RADAR_SNAPSHOT_DIR = $oldSnap; $env:HTTP_PROXY = $oldHttp; $env:HTTPS_PROXY = $oldHttps; $env:ALL_PROXY = $oldAll; $env:NO_PROXY = $oldNo
}