"""Dicionario das funcionalidades. Para adicionar uma: crie a pasta em
app/modules/<nome> com routes.py expondo `router`, e registre o nome aqui."""
from importlib import import_module

from app.core.config import get_settings

# Nao podem ser desligados: sem eles o sistema nao funciona com seguranca.
REQUIRED = ["autenticacao", "auditoria", "contas", "lancamentos"]
OPTIONAL = [
    "painel", "dividas", "financiamentos", "investimentos", "objetivos",
    "reserva", "desafios", "orcamento", "relatorios", "previsao", "alertas", "conciliacao", "holerites",
]


def enabled_modules() -> list[str]:
    disabled = get_settings().disabled_module_set
    return REQUIRED + [m for m in OPTIONAL if m not in disabled]


def load_all_models() -> None:
    """Todos os modelos, inclusive de modulos desligados: o banco e um so."""
    for name in REQUIRED + OPTIONAL:
        try:
            import_module(f"app.modules.{name}.models")
        except ModuleNotFoundError as error:
            if error.name != f"app.modules.{name}.models":
                raise
    import_module("app.core.calc_graph")
    import_module("app.core.jobs")


def routers() -> list:
    return [import_module(f"app.modules.{name}.routes").router for name in enabled_modules()]
