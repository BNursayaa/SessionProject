Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Push-Location (Join-Path $PSScriptRoot "..\\backend")
try {
  python -m app.main
} finally {
  Pop-Location
}

