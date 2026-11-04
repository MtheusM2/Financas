from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str
    secret_key: str
    allowed_emails: str = ""

    email_backend: str = "smtp"  # smtp | memory | file
    email_file: str = "/tmp/emails.jsonl"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    code_ttl_seconds: int = 60
    code_max_resends: int = 5
    code_lock_minutes: int = 15
    code_max_attempts: int = 5

    login_max_attempts: int = 5
    login_lock_minutes: int = 15
    session_days: int = 30

    cookie_secure: bool = True
    disabled_modules: str = ""

    backup_key: str = ""
    backup_dir: str = "/backups"
    backup_keep: int = 30

    @property
    def allowed_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}

    @property
    def disabled_module_set(self) -> set[str]:
        return {m.strip() for m in self.disabled_modules.split(",") if m.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
