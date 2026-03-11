Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Push-Location (Join-Path $PSScriptRoot "..\\gateway")
try {
  python .\\gateway.py --simulate
} finally {
  Pop-Location
}

