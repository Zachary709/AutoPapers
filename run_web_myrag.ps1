$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$env:CONDA_NO_PLUGINS = "true"
$env:PYTHONPATH = Join-Path $repoRoot "src"

conda run -n myrag python -m autopapers serve --host 127.0.0.1 --port 8876
