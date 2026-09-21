Set-Location "$PSScriptRoot"
$env:PYTHONPATH = "$PSScriptRoot"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 18765
