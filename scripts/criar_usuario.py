"""Cria (ou atualiza) um usuario do sistema direto no banco.

Serve para cadastrar gente sem precisar abrir a tela de administracao, que e o
caso quando o usuario novo precisa existir logo depois de subir uma versao na
VM. O script e IDEMPOTENTE: rodar duas vezes nao duplica nem quebra nada.

Exemplos (dentro da pasta do projeto, com a .venv ativa):

    # usa o banco padrao do projeto
    python scripts/criar_usuario.py --id sirlandia --nome Sirlandia --perfil gerente

    # na VM, apontando para o banco de producao
    $env:DATABASE_URL = "sqlite:///C:/data/gerenciado-contabil/controle_contabil.db"
    python scripts/criar_usuario.py --id sirlandia --nome Sirlandia --perfil gerente

O usuario criado ja nasce com `must_change_password = True`, ou seja: entra
uma vez com a senha provisoria e o proprio sistema o obriga a definir a dele.
"""

from __future__ import annotations

import argparse
import secrets
import string
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


def gerar_senha(tamanho: int = 12) -> str:
    """Senha provisoria legivel: sem caracteres que confundem (l, I, 0, O)."""
    alfabeto = (string.ascii_letters + string.digits).translate(
        str.maketrans("", "", "lI0O")
    )
    return "".join(secrets.choice(alfabeto) for _ in range(tamanho))


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria ou atualiza um usuario do sistema.")
    parser.add_argument("--id", required=True, help="Login (ex.: sirlandia).")
    parser.add_argument("--nome", help="Nome exibido. Padrao: o proprio --id.")
    parser.add_argument(
        "--perfil",
        default="equipe",
        choices=["gerente", "equipe"],
        help="gerente = ve todas as categorias; equipe = ve apenas a sua.",
    )
    parser.add_argument(
        "--categoria",
        default=None,
        help="Obrigatorio para perfil 'equipe'. Ignorado para 'gerente'.",
    )
    parser.add_argument(
        "--senha",
        default=None,
        help="Senha provisoria. Se omitida, uma senha aleatoria e gerada e impressa.",
    )
    parser.add_argument(
        "--sem-troca-obrigatoria",
        action="store_true",
        help="Nao exige a troca de senha no primeiro acesso.",
    )
    parser.add_argument(
        "--atualizar-senha",
        action="store_true",
        help="Se o usuario ja existir, redefine a senha dele em vez de so avisar.",
    )
    args = parser.parse_args()

    from app import crud, logic, models, schemas, security
    from app.database import Base, engine, session_scope

    user_id = args.id.strip()
    nome = (args.nome or user_id).strip()
    perfil = args.perfil
    categoria = None if perfil == "gerente" else args.categoria

    if perfil == "equipe" and categoria not in logic.CATEGORIES:
        raise SystemExit(
            "Para perfil 'equipe' informe --categoria entre: "
            + ", ".join(logic.CATEGORIES)
        )

    senha = args.senha or gerar_senha()
    exige_troca = not args.sem_troca_obrigatoria

    Base.metadata.create_all(bind=engine)
    with session_scope() as db:
        # Garante que a coluna must_change_password existe mesmo em bancos
        # criados por versoes anteriores do sistema.
        crud.ensure_schema(db)

        existente = crud.get_user(db, user_id)
        if existente:
            print(f"ja_existia={user_id} perfil={existente.perfil} nome={existente.nome}")
            if not args.atualizar_senha:
                print("nada_alterado=true (use --atualizar-senha para redefinir a senha)")
                return
            existente.senha = security.hash_password(senha)
            existente.must_change_password = exige_troca
            print(f"senha_redefinida={user_id}")
        else:
            cor = logic.AVATAR_COLORS[
                db.query(models.User).count() % len(logic.AVATAR_COLORS)
            ]
            crud.create_user(
                db,
                schemas.UserCreate(
                    id=user_id,
                    nome=nome,
                    senha=senha,
                    perfil=perfil,
                    categoria=categoria,
                ),
                cor,
                must_change_password=exige_troca,
            )
            print(f"criado={user_id} nome={nome} perfil={perfil} categoria={categoria or '-'}")

    print(f"senha_provisoria={senha}")
    print(f"troca_obrigatoria_no_primeiro_acesso={str(exige_troca).lower()}")


if __name__ == "__main__":
    main()
