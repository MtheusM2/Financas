# Sobe o sistema inteiro em um banco descartavel e roda os testes de tela (PC, Android e iPhone).
$env:Path = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:Path"
$saida = Join-Path $env:TEMP "financas-e2e.txt"
$compose = "docker compose -f docker-compose.test.yml --profile e2e"
cmd /c "$compose down -v >nul 2>&1"
cmd /c "$compose build > ""$saida"" 2>&1"
if ($LASTEXITCODE -ne 0) { Get-Content $saida -Tail 40; exit $LASTEXITCODE }
cmd /c "$compose up --abort-on-container-exit --exit-code-from e2e e2e > ""$saida"" 2>&1"
$codigo = $LASTEXITCODE
if ($codigo -ne 0) { cmd /c "$compose logs api > ""$saida.api"" 2>&1" }
cmd /c "$compose down -v >nul 2>&1"
Get-Content $saida | Where-Object { $_ -match '^e2e|error|Error' } | ForEach-Object { if ($_.Length -gt 400) { $_.Substring(0, 400) } else { $_ } } | Select-Object -Last 60
exit $codigo
