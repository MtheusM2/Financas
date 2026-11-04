# Finanças do Casal

Sistema web privado para organizar salários, gastos, dívidas, investimentos, objetivos e desafios. Roda em Docker no PC de casa e é acessado pelo navegador do PC, do Android e do iPhone, sempre pela VPN Tailscale.

## Instalar

### 1. Criar o arquivo de configuração
Copie `.env.example` para `.env`. Para gerar um valor aleatório, rode o comando abaixo uma vez para cada um destes campos: `POSTGRES_PASSWORD`, `SECRET_KEY` e `BACKUP_KEY`.

```bash
[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }))
```

Depois, preencha:
- `ALLOWED_EMAILS`: os e-mails que podem se cadastrar;
- `SMTP_USER` e `SMTP_FROM`: o Gmail remetente;
- `SMTP_PASSWORD`: a senha de app de 16 letras do Google;
- `BACKUP_PATH`: a pasta do Windows que recebe os backups. O Docker cria a pasta se ela não existir.

**Guarde o `BACKUP_KEY` fora deste PC.** Sem ele, os backups não podem ser abertos.

### 2. Subir o sistema

```bash
docker compose up -d --build
```

Ele fica em `http://localhost:8080`, disponível só neste PC.

### 3. Liberar pela VPN

```bash
tailscale serve --bg 8080
```

O comando mostra o endereço `https://...ts.net`. É ele que vocês usam em todos os aparelhos, com o Tailscale ligado.

### 4. Instalar nos celulares
- **Android (Chrome):** menu ⋮ > Instalar app.
- **iPhone (Safari):** Compartilhar > Adicionar à Tela de Início.

## Proteger os dados no PC
- Ative o **BitLocker** no Windows. O banco fica no disco do PC, e o BitLocker protege esses dados se o aparelho for roubado.
- O banco fica no volume `db-data` do Docker e continua lá depois de desligar o PC. Nunca use `docker compose down -v`, porque o `-v` apaga esse volume.
- Os backups ficam criptografados na pasta `BACKUP_PATH`, fora do Docker. Copie essa pasta para fora do PC, como um HD externo, porque uma falha no disco atingiria o banco e os backups juntos.
- Se `BACKUP_PATH` ficar em uma pasta do OneDrive, mantenha o `.env` fora do OneDrive, porque ele guarda o `BACKUP_KEY`. Nunca coloque o banco em uma pasta sincronizada.

## Usar no dia a dia

### Salário e outras rendas
Em **Lançamentos > Salário e outras rendas**, cada pessoa cadastra a própria renda. Em "Todo mês", adicione uma data para cada recebimento: cada uma repete no mesmo dia dos próximos meses e conta como recebida quando a data chega. Freela ou extra usa "Só desta vez".

### Dívidas e contas fixas
- Cadastrar uma dívida não mexe no saldo. Ela entra na previsão, avisa 7 dias antes de vencer e só é descontada quando você registra o pagamento.
- Cada pagamento quita o vencimento mais antigo em aberto. Um mês não pago continua como atrasado na virada do mês.
- Na hora de pagar, informe a data e o valor real. Se errar, use **Desfazer último pagamento**.
- A tag vem de **Ajustes > Categorias e tags**, e os pagamentos entram nos tetos dela.
- Financiamentos seguem as mesmas regras de aviso e atraso. Cada parcela registrada quita a mais antiga em aberto.
- **Encerrar** tira a dívida dos avisos e da previsão e mantém os pagamentos. **Excluir** apaga a dívida e os pagamentos dela. Para excluir várias, marque as caixas e use **Excluir selecionadas**.

### Importar extrato
Em **Importar e conciliar**, envie o arquivo OFX ou CSV exportado do banco. Linhas já lançadas são conciliadas, e importar o mesmo arquivo de novo não duplica.

### Caixa e competência
- **Data:** quando o dinheiro entra ou sai (caixa).
- **Competência:** o mês a que o valor pertence, quando for diferente.
- **Previsto:** ainda não pago ou recebido. Não mexe no saldo real, mas entra na previsão e nos alertas.

### Personalizar
Em **Ajustes**, cada pessoa escolhe os blocos do painel, renomeia a conta compartilhada, oculta contas e define os alertas por e-mail.

## Operação

### Restaurar um backup
O arquivo precisa estar na pasta `BACKUP_PATH`, que o sistema enxerga como `/backups`.

```bash
docker compose exec worker python -m app.core.backup restaurar /backups/NOME-DO-ARQUIVO.sql.enc
```

### Zerar os dados
Apaga os dados financeiros, depois de fazer um backup. Logins, contas e categorias continuam, e o comando pede confirmação.

```bash
powershell -ExecutionPolicy Bypass -File .\zerar-dados.ps1
```

### Ver os logs

```bash
docker compose logs -f api worker
```

Cada resposta traz o cabeçalho `X-Rastreio`, com o mesmo código dos logs. Em **Ajustes > Histórico** aparece quem alterou o quê.

### Atualizar depois de mudar o código

```bash
docker compose up -d --build
```

As migrações do banco rodam sozinhas antes da API subir.

## Testes
- `testar-backend.ps1`: regras, cálculos, privacidade, fila e backup.
- `testar-telas.ps1`: fluxo completo em tamanho de PC, Android e iPhone.
- `testar-carga.ps1`: carga com queda de uma cópia da API.

## Adicionar uma funcionalidade
1. Crie a pasta `backend/app/modules/<nome>`, com `routes.py` expondo `router`.
2. Registre o nome em `backend/app/core/registry.py`.
3. Se criar tabelas, gere a migração:

```bash
docker compose run --rm migrate alembic revision --autogenerate -m "descricao"
```

4. Para desligar uma funcionalidade sem apagar dados, use `DISABLED_MODULES` no `.env`.

Toda consulta a dados de usuário deve passar por `visible_clause`, `get_visible` ou `tx_filter`, e cada rota nova de leitura deve entrar em `test_privacidade.py`.

## Limites conhecidos
- **Sem conexão direta com bancos:** a integração automática exige um agregador de Open Finance, normalmente pago. A conciliação usa arquivos do banco e, por ter módulo próprio, pode ganhar um conector depois.
- **Disponibilidade:** o sistema só abre com o PC ligado. Para deixar sempre no ar, leve os mesmos contêineres para um servidor.
- **Imposto de Renda:** o relatório ajuda no preenchimento, mas não substitui os informes oficiais nem um contador.
- **Investimentos:** o valor atual é informado por vocês.
