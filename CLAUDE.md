# Finanças do Casal

Sistema web privado para um casal organizar rendas, gastos, dívidas, financiamentos, investimentos, objetivos e desafios. Roda em Docker no PC de casa e é acessado só pela VPN Tailscale, no PC, no Android e no iPhone. O uso, a instalação e a operação estão no [README.md](README.md).

Escreva para o dono do projeto em português, de forma simples, e dê instruções passo a passo: ele não é da área de sistemas.

## Este sistema está em uso, com dados reais
- O projeto `financas` é o sistema real. Os testes usam o projeto separado `financas-test`, em um banco descartável.
- **Nunca rode `docker compose down -v` no projeto real.** O `-v` apaga o banco, que fica no volume `db-data`.
- Não apague nem altere dados reais sem pedir. Para investigar, use só consultas de leitura.
- Antes de atualizar o sistema real, rode os testes e faça um backup. Na ordem:

```bash
docker compose exec -T worker python -m app.core.backup
```

```bash
docker compose up -d --build
```

## Segurança
- Nunca mostre no chat nem grave em logs os valores do `.env`. Ao conferir esse arquivo, informe só se o campo está preenchido.
- O dono preenche as senhas e faz os ajustes do Windows e das contas Google e Tailscale. Dê as instruções.
- O projeto fica fora do OneDrive de propósito, porque o `.env` guarda o `BACKUP_KEY`. O banco nunca deve ficar em uma pasta sincronizada.
- Dados ocultos não podem aparecer para a outra pessoa por nenhuma rota. Toda consulta a dados de usuário passa por `visible_clause`, `get_visible` ou `tx_filter`, e cada rota nova de leitura entra em `test_privacidade.py`.

## Estrutura
- `backend/app/core`: configuração, banco, fila, worker, backup, visibilidade e registro de módulos.
- `backend/app/modules/<nome>`: uma pasta por funcionalidade, com rotas, regras e testes. Registre módulos novos em `core/registry.py`.
- `backend/alembic/versions`: migrações. Toda mudança de tabela precisa de uma.
- `frontend/src/pages`: uma tela por funcionalidade. `ui.jsx` tem os formulários, e `charts.jsx`, os gráficos em SVG.
- `frontend/e2e/fluxo.spec.js`: testes de tela em tamanho de PC, Android e iPhone.

## Regras do domínio
- Dinheiro sempre em centavos inteiros. Cálculos ficam em funções puras.
- Todo lançamento nasce em `add_transaction`, e toda escrita em lançamentos chama `after_change`, que mantém os totais mensais.
- Cadastrar uma dívida não mexe no saldo. Ela entra na previsão, avisa 7 dias antes e só é descontada ao registrar o pagamento.
- Cada pagamento de dívida ou financiamento quita o vencimento mais antigo em aberto (`due_status` nos dois módulos). Um mês não pago continua atrasado.
- Renda mensal vira uma regra recorrente por data e conta como recebida quando a data chega. "Só desta vez" cria um lançamento único.
- "Tag" e "categoria" são a mesma coisa no sistema.
- Filtre as entradas no front-end com Zod e valide de novo no back-end.

## Testes
Rode no PowerShell, a partir desta pasta:

```bash
.\testar-backend.ps1
```

```bash
.\testar-telas.ps1
```

```bash
.\testar-carga.ps1
```

O simulador de iPhone às vezes não alcança botões depois que um formulário abre ou fecha. Por isso, o teste usa `tap`, que pode simular o clique. A rolagem real é conferida no aparelho.

## Limites conhecidos
- Sem conexão direta com bancos, porque Open Finance exige um agregador pago. A conciliação usa arquivos OFX e CSV.
- Renda mensal repete no mesmo dia do mês e não calcula "5º dia útil".
