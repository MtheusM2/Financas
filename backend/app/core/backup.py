"""Backup criptografado do banco. Restaurar: python -m app.core.backup restaurar ARQUIVO"""
import base64
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.core.db import now


def _fernet() -> Fernet:
    key = get_settings().backup_key
    if not key:
        raise RuntimeError("BACKUP_KEY não configurada")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def _pg_args() -> tuple[list[str], dict]:
    url = make_url(get_settings().database_url)
    args = ["-h", url.host, "-p", str(url.port or 5432), "-U", url.username, "-d", url.database]
    return args, {**os.environ, "PGPASSWORD": url.password or ""}


def run_backup() -> Path:
    settings = get_settings()
    args, env = _pg_args()
    dump = subprocess.run(["pg_dump", "--clean", "--if-exists", *args], capture_output=True, env=env, check=True)
    folder = Path(settings.backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"financas-{now():%Y%m%d-%H%M%S}.sql.enc"
    path.write_bytes(_fernet().encrypt(dump.stdout))
    for old in sorted(folder.glob("financas-*.sql.enc"))[: -settings.backup_keep]:
        old.unlink()
    return path


def restore(path: Path) -> None:
    args, env = _pg_args()
    sql = _fernet().decrypt(path.read_bytes())
    subprocess.run(["psql", "-v", "ON_ERROR_STOP=1", "-q", *args], input=sql, env=env, check=True, capture_output=True)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "restaurar":
        restore(Path(sys.argv[2]))
    else:
        print(run_backup())
