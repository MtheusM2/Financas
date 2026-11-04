-- Apaga os dados financeiros e mantem contas de login, contas, categorias e historico.
-- Sem CASCADE de proposito: se uma tabela nova depender destas, o comando falha em vez de apagar a mais.
TRUNCATE transactions, monthly_totals, recurring_rules, debts, financing_extras, financings,
         investments, goals, challenges, category_budgets, import_rules, month_closings, reconciliations,
         payslips, fgts_balances
         RESTART IDENTITY;
UPDATE accounts SET opening_balance_cents = 0;
INSERT INTO audit_logs (at, user_id, action, entity, entity_id, request_id, private, changes)
VALUES (now(), NULL, 'zerou_dados', 'sistema', NULL, 'zerar-dados', false, NULL);
