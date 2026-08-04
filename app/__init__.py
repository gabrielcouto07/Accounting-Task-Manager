"""Controle de Obrigacoes Contabeis FastAPI app."""

import os
from pathlib import Path


def _load_env_file() -> None:
    """Carrega variaveis de um arquivo .env na raiz do projeto, se existir.

    Variaveis ja definidas no ambiente do processo tem prioridade sobre o
    arquivo. Util em servidores onde o processo e iniciado por um agendador
    que nao repassa variaveis de maquina recem-criadas.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        content = env_path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env_file()
