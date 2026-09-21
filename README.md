# Gerenciado Contabil

Aplicacao FastAPI para controle de obrigacoes contabeis, subtarefas, usuarios e acompanhamento por categoria.

## Estrutura

- `app/`: aplicacao web, templates, logica e acesso a dados.
- `scripts/`: importacao, backup e checks locais.
- `docs/`: guias de deploy e operacao.
- `backups/`: exportacoes e artefatos de migracao.

## Rodando localmente

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Check antes de subir mudancas

```powershell
python scripts\check_project.py
```

Esse comando compila o codigo Python e roda um smoke test isolado em um banco temporario.

Se voce ainda estiver validando a migracao inicial do banco legado, rode tambem:

```powershell
python scripts\check_project.py --verify-migration
```

## VS Code

Se o editor estiver mostrando imports vermelhos, garanta que:

1. A pasta aberta no VS Code e a raiz deste projeto.
2. O interpretador Python selecionado seja o da `.venv`.
3. As dependencias de `requirements.txt` estejam instaladas.

O arquivo `pyrightconfig.json` foi adicionado para ajudar o Pylance a resolver `from app import ...`.

## Documentacao

- [docs/ATUALIZACAO_2026-09_EXPLICADA.md](docs/ATUALIZACAO_2026-09_EXPLICADA.md):
  o que mudou na versao de setembro/2026, por que, e a sintaxe explicada.
- [docs/deployment_vm_lan.md](docs/deployment_vm_lan.md): deploy e atualizacao na VM.
- `.env.example`: modelo das variaveis de configuracao.

## Criar usuario pela linha de comando

```powershell
python scripts\criar_usuario.py --id sirlandia --nome "Sirlandia" --perfil gerente
python scripts\criar_usuario.py --id joao --nome "Joao Silva" --perfil equipe --categoria fiscal
```

O usuario nasce com senha provisoria e e obrigado a definir a propria senha no
primeiro acesso.

## Deploy em VM da rede local

O guia principal esta em [docs/deployment_vm_lan.md](docs/deployment_vm_lan.md).

Para atualizacoes futuras, prefira manter o banco SQLite fora da pasta do codigo usando `DATABASE_URL`. Assim voce consegue trocar o codigo da VM sem misturar dados de producao com os arquivos da aplicacao.
