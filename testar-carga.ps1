# Carga com 2 copias da API. No meio do teste, derruba uma copia para ver o sistema continuar no ar.
$env:Path = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:Path"
$compose = "docker compose -f docker-compose.test.yml --profile e2e"
$saida = Join-Path $env:TEMP "financas-carga.txt"
cmd /c "$compose down -v >nul 2>&1"
cmd /c "$compose up -d --build web > ""$saida"" 2>&1"
Start-Sleep -Seconds 8

# Cria a conta de teste pela propria API e le o codigo do arquivo de e-mails de teste.
$prepara = @'
import json, httpx
c = httpx.Client(base_url="http://web", headers={"X-Financas": "1"})
c.post("/api/autenticacao/cadastro", json={"email": "ana@teste.com", "name": "Ana", "password": "senha-bem-longa-1"}).raise_for_status()
code = json.loads(open("/emails/emails.jsonl").read().strip().split("\n")[-1])["body"].split()[3].rstrip(".")
c.post("/api/autenticacao/verificar", json={"email": "ana@teste.com", "code": code}).raise_for_status()
print("conta criada")
'@
$arquivo = Join-Path $env:TEMP "financas-prepara.py"
Set-Content -Path $arquivo -Value $prepara -Encoding ascii
cmd /c "docker cp ""$arquivo"" financas-test-api-1:/tmp/prepara.py"
cmd /c "docker exec financas-test-api-1 python /tmp/prepara.py 2>&1"

$carga = Start-Job -ScriptBlock {
  param($p)
  $env:Path = $p
  cmd /c "docker exec financas-test-api-1 python /app/scripts/carga.py http://web ana@teste.com senha-bem-longa-1 40 2>&1"
} -ArgumentList $env:Path
Start-Sleep -Seconds 15
Write-Output "Derrubando a copia 2 da API, com a carga em andamento..."
cmd /c "docker kill financas-test-api-2 2>&1"
Wait-Job $carga -Timeout 120 | Out-Null
Receive-Job $carga
cmd /c "$compose down -v >nul 2>&1"
