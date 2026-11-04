# Roda os testes do back-end em um banco descartavel.
$env:Path = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:Path"
$saida = Join-Path $env:TEMP "financas-pytest.txt"
cmd /c "docker compose -f docker-compose.test.yml --profile backend down -v >nul 2>&1"
# Reconstroi a imagem antes: assim bibliotecas novas do requirements.txt entram nos testes.
cmd /c "docker compose -f docker-compose.test.yml --profile backend build backend > ""$saida"" 2>&1"
if ($LASTEXITCODE -ne 0) { Get-Content $saida | Select-Object -Last 30; exit $LASTEXITCODE }
cmd /c "docker compose -f docker-compose.test.yml --profile backend run --rm backend python -m pytest -q --tb=short --show-capture=no --import-mode=importlib -p no:cacheprovider app $args > ""$saida"" 2>&1"
$codigo = $LASTEXITCODE
cmd /c "docker compose -f docker-compose.test.yml --profile backend down -v >nul 2>&1"
Get-Content $saida | Where-Object { $_ -notmatch '^(/usr/local/lib|Container| Container|\s+Container)' } | Select-Object -Last 70
exit $codigo
