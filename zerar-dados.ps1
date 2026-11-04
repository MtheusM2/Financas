# Faz um backup e apaga os dados financeiros do sistema real. Mantem logins, contas e categorias.
$env:Path = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:Path"
Set-Location $PSScriptRoot

Write-Output "Isto apaga lancamentos, rendas, dividas, financiamentos, investimentos, objetivos, desafios e tetos."
Write-Output "Logins, contas e categorias continuam. Um backup sera feito antes."
$resposta = Read-Host "Digite ZERAR para continuar"
if ($resposta -cne "ZERAR") { Write-Output "Cancelado. Nada foi alterado."; exit 1 }

Write-Output "Fazendo o backup..."
docker compose exec -T worker python -m app.core.backup
if ($LASTEXITCODE -ne 0) { Write-Output "O backup falhou. Nada foi apagado."; exit 1 }

Get-Content -Raw "backend\scripts\zerar_dados.sql" | docker compose exec -T db psql -U financas -d financas -q -1 -v ON_ERROR_STOP=1
if ($LASTEXITCODE -ne 0) { Write-Output "Falhou. Nada foi apagado."; exit 1 }

# A API guarda calculos em memoria: reiniciar garante que nada antigo apareca.
docker compose restart api worker
Write-Output "Pronto. Os dados foram zerados."
