# Estado da VM srvapp01 - Gerenciado Contabil

Documento levantado durante o deploy do commit `fc88708` em **21/09/2026**.
Tudo aqui foi verificado por comando na propria VM, nao e suposicao.

Objetivo: no proximo update, nao repetir as 2h de investigacao que este deploy
custou.

---

## 1. Resumo executivo - o que mudou neste deploy

| Antes (21/09 manha) | Depois |
| --- | --- |
| Banco em `C:\Gerenciado Contabil\controle_contabil.db` | Banco em `C:\data\gerenciado-contabil\controle_contabil.db` |
| Commit `153c2d0` | Commit `fc88708` |
| `.env` sem `DATABASE_URL` | `.env` com `DATABASE_URL` + variavel de maquina |
| Senhas em texto puro no `.db` | Senhas em hash PBKDF2 |
| Sem `users.must_change_password` / `tasks.solicitante` | Colunas criadas |

**Nenhum dado perdido.** Contagens identicas antes e depois:
`users=6`, `tasks=311`, `subtasks=997`, `chamados=5`.

---

## 2. A informacao mais importante deste documento

### O sistema NAO sobe pela tarefa agendada. Sobe por um servico NSSM.

```powershell
# ISTO e o que controla a aplicacao:
Stop-Service  -Name "TaskManagerPython"
Start-Service -Name "TaskManagerPython"
```

| Item | Valor |
| --- | --- |
| Nome do servico | `TaskManagerPython` |
| Gerenciador | NSSM - `C:\Tools\NSSM\nssm.exe` |
| StartMode | `Automatic` |
| Processo pai observado | PID 2220 (`nssm.exe`) |

O NSSM existe para **ressuscitar processos**. Matar o python filho com
`Stop-Process` nao funciona: em ~40 segundos ele volta com PID novo. Neste
deploy isso aconteceu **quatro vezes** (PIDs 2244, 1876/3508, 5512/7988, 8116)
antes de descobrirmos a causa.

### A tarefa agendada `GerenciadoContabil` e um resquico - deixe DESABILITADA

Ela existe, roda como SYSTEM com `-RunLevel Highest`, trigger `AtStartup`, e
tem `RestartCount 3` / `RestartInterval PT1M`. **Nao e o mecanismo real.** Se
ela for habilitada, dois launchers disputam a porta 8000.

```powershell
Disable-ScheduledTask -TaskName "GerenciadoContabil"
```

Detalhe tecnico: `Set-ScheduledTask -Settings (... -RestartCount 0)` **falha**
com `The task XML is missing a required element or attribute. (41,8):Count:`.
Nao insista nesse caminho - a tarefa nao precisa ser corrigida, precisa ficar
desabilitada.

---

## 3. Inventario da instalacao

### Caminhos

| Item | Caminho |
| --- | --- |
| Codigo (clone git) | `C:\Gerenciado Contabil` |
| Banco de producao | `C:\data\gerenciado-contabil\controle_contabil.db` |
| Configuracao | `C:\Gerenciado Contabil\.env` |
| Python do servico | `C:\Gerenciado Contabil\venv\Scripts\python.exe` (3.13.2) |
| NSSM | `C:\Tools\NSSM\nssm.exe` |
| Backups deste deploy | `C:\backups-deploy\20260921-1643` |
| Ferramentas auxiliares | `C:\deploy-tools\` |

### Aplicacao

- FastAPI + uvicorn: `app.main:app --host 0.0.0.0 --port 8000`
- Repositorio: `https://github.com/gabrielcouto07/Accounting-Task-Manager`, branch `main`
- Commit atual: `fc887088a45a9ed87857c7087be9090c6e8f80c2`
- Commit anterior (rollback): `153c2d07544cf130cf44ef6181bdfe4b592b5384`
- SQLite em modo **WAL**

### Conteudo do `.env` (4 linhas, 212 bytes, ASCII sem BOM)

```
SMTP_USER=chamados@scientificdental.com
SMTP_PASSWORD=<omitido>
SESSION_SECRET_KEY=<omitido>
DATABASE_URL=sqlite:///C:/data/gerenciado-contabil/controle_contabil.db
```

Variavel de maquina redundante (cinto e suspensorio), porque o servico roda
como SYSTEM e a leitura do `.env` so existe a partir do commit `153c2d0`:

```powershell
[Environment]::GetEnvironmentVariable("DATABASE_URL","Machine")
# sqlite:///C:/data/gerenciado-contabil/controle_contabil.db
```

### Estrutura da pasta do codigo

```
.git/  app/  docs/  scripts/  backups/  venv/  .venv/  logs/  .agents/
.env  .gitignore  migrar.py  run_debug.py  requirements.txt
pyrightconfig.json  README.md
```

Nota: existem **duas** venvs (`venv` e `.venv`). A usada pelo servico e
`venv`. A `.venv` (09/07) aparenta ser resto de teste.

### Processos python na VM que NAO sao esta aplicacao

Nao mate estes - sao outra aplicacao:

```
PID 1472 / 7460 -> C:\Apps\CanalCompliance\venv\Scripts\python.exe serve.py
```

---

## 4. A armadilha do banco legado (causou um incidente neste deploy)

`C:\Gerenciado Contabil\app\controle.db` e o banco do **sistema antigo**. O
codigo o importa automaticamente **quando a tabela `tasks` esta vazia**.

### O que aconteceu em 21/09

1. `.env` foi editado com o novo `DATABASE_URL` apontando para `C:\data\`
2. `C:\data\gerenciado-contabil\` estava **vazia** naquele momento
3. O servico NSSM (que ninguem sabia que existia) reiniciou a aplicacao
4. A app criou um banco novo vazio em `C:\data\` e **importou o legado**
5. O dashboard passou a mostrar **78 obrigacoes** com nomes reais de clientes
   e vencimentos de julho - parecia funcionar perfeitamente
6. O `Move-Item` do banco real falhou com `Cannot create a file when that file
   already exists` - **esse erro salvou os dados**

**Licao:** nunca deixe `DATABASE_URL` apontando para uma pasta vazia com a
aplicacao capaz de subir. Ou o servico esta parado, ou o banco ja esta no
destino.

**Licao 2:** um dashboard que abre e mostra dados plausiveis **nao** prova que
o banco certo esta em uso. Confira sempre pela contagem de `tasks` (311).

---

## 5. Procedimento para o PROXIMO update

Com o banco fora da pasta do codigo, ficou curto. Janela real: ~5 minutos.

### 5.1 Antes de parar (sistema no ar, sem downtime)

```powershell
cd "C:\Gerenciado Contabil"
git status --porcelain            # tem que vir vazio
git fetch origin
git log --oneline HEAD..origin/main
git log -1 --pretty="%H %s"       # ANOTE: commit do rollback

# backup a quente, via API do SQLite (funciona com o servico rodando)
$d = "C:\backups-deploy\" + (Get-Date -Format "yyyyMMdd-HHmm")
New-Item -ItemType Directory -Force -Path $d | Out-Null
.\venv\Scripts\python.exe "C:\deploy-tools\backup_direto.py" `
  "C:\data\gerenciado-contabil\controle_contabil.db" "$d\consolidado.db"
Copy-Item "C:\Gerenciado Contabil\.env" "$d\.env.bak"
```

Confira `BACKUP_OK` e as contagens. **Copie `$d` para fora da VM.**
Anote o caminho de `$d` **em papel** - a variavel morre com a janela.

### 5.2 Janela de manutencao

```powershell
# parar
Stop-Service -Name "TaskManagerPython" -Force
Start-Sleep -Seconds 10
Get-Service -Name "TaskManagerPython" | Select-Object Status      # Stopped
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue   # vazio

# atualizar
cd "C:\Gerenciado Contabil"
git pull --ff-only origin main
git log -1 --pretty="%H %s"
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# subir
Start-Service -Name "TaskManagerPython"
Start-Sleep -Seconds 20
Get-Service -Name "TaskManagerPython" | Select-Object Status, StartType
(Invoke-WebRequest http://localhost:8000/health -UseBasicParsing).StatusCode
```

### 5.3 Conferencia

```powershell
# contagens - comparar com as do 5.1
.\venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('file:C:/data/gerenciado-contabil/controle_contabil.db?mode=ro',uri=True); [print(t.ljust(10),'=',c.execute('select count(*) from '+t).fetchone()[0]) for t in ('users','tasks','subtasks','chamados')]; c.close()"

# nao pode nascer banco na pasta do codigo
Get-ChildItem "C:\Gerenciado Contabil\controle_contabil.db*" -ErrorAction SilentlyContinue
```

Criterio de sucesso: **`tasks` = 311** (ou o numero atual), e nada novo em
`C:\Gerenciado Contabil\`.

### 5.4 Rollback

```powershell
Stop-Service -Name "TaskManagerPython" -Force

# Caso A - so o codigo esta errado (dados intactos)
git reset --hard <COMMIT_ANOTADO>

# Caso B - voltar tambem os dados
Remove-Item "C:\data\gerenciado-contabil\controle_contabil.db-wal" -ErrorAction SilentlyContinue
Remove-Item "C:\data\gerenciado-contabil\controle_contabil.db-shm" -ErrorAction SilentlyContinue
Copy-Item "$d\consolidado.db" "C:\data\gerenciado-contabil\controle_contabil.db" -Force

Start-Service -Name "TaskManagerPython"
```

Apagar `-wal`/`-shm` antigos e **obrigatorio**: o SQLite tentaria aplicar um
WAL que nao pertence ao `.db` restaurado.

---

## 6. Pegadinhas tecnicas encontradas (para nao repetir)

### O tamanho do `-wal` nao e o tamanho do dado novo

O `-wal` tinha **4.124.152 bytes** contra 405.504 do `.db`. Apos
`wal_checkpoint(truncate)`, o `.db` foi para **413.696** - apenas +8 KB. O WAL
acumula copias repetidas das mesmas paginas a cada transacao; nao e dado novo
acumulado.

Nao se assuste com o crescimento pequeno - valide pelas **contagens**, nao
pelo tamanho.

### Checkpoint correto antes de mover o arquivo

```powershell
.\venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect(r'CAMINHO.db'); print(c.execute('pragma wal_checkpoint(truncate)').fetchone()); print(c.execute('pragma journal_mode=delete').fetchone()); c.close()"
Get-ChildItem "CAMINHO.db*"     # tem que sobrar SOMENTE o .db
```

Resultado esperado: `(0, 0, 0)` e `('delete',)`. Se sobrar `-wal` ou `-shm`,
alguem tem o banco aberto - **nao mova nada**.

### Variavel do PowerShell dentro de `python -c` quebra

`"...'file:'+r'$dest\arquivo.db'..."` - o PowerShell expande `$dest` **antes**
de passar ao Python. Se a variavel estiver vazia, sobra `\arquivo.db` e da
`unable to open database file`. Passe caminhos como **argumentos** (`sys.argv`),
nunca interpolados no codigo.

### `Get-ChildItem` truncando nomes

Use sempre `| Format-Table Name, Length, LastWriteTime -AutoSize`. Com
`Select-Object` puro os nomes saem como `controle_conta...` e voce nao valida
nada.

### Um unico check de porta nao prova nada

Neste deploy, `Get-NetTCPConnection` veio vazio 5 segundos depois do kill e o
processo voltou 40 segundos depois. Se for matar processo (o que nao deve mais
ser necessario), confira **duas vezes com 45s de intervalo**.

### `Move-Item` sem `-Force` e um aliado

Ele falhou ao tentar sobrescrever o banco importado e evitou a perda. Nao use
`-Force` ao mover bancos para um destino que voce nao verificou.

---

## 7. Pendencias em aberto (risco residual)

### 7.1 NSSM pode ter `DATABASE_URL` proprio - VERIFICAR

Esta e a pendencia mais importante. O NSSM tem variaveis de ambiente proprias
(`AppEnvironmentExtra`) que vencem o `.env`. Se houver ali um `DATABASE_URL`
apontando para o caminho antigo, **um reboot pode recriar o problema do item 4**.

```powershell
C:\Tools\NSSM\nssm.exe get TaskManagerPython AppEnvironmentExtra
C:\Tools\NSSM\nssm.exe get TaskManagerPython AppDirectory
C:\Tools\NSSM\nssm.exe get TaskManagerPython Application
C:\Tools\NSSM\nssm.exe get TaskManagerPython AppParameters
```

Se aparecer um `DATABASE_URL` antigo:

```powershell
C:\Tools\NSSM\nssm.exe set TaskManagerPython AppEnvironmentExtra "DATABASE_URL=sqlite:///C:/data/gerenciado-contabil/controle_contabil.db"
```

### 7.2 Teste de reboot

Nunca foi validado que apos reiniciar a VM o servico sobe **e** abre o banco
em `C:\data\`. Fazer em janela controlada, conferindo `tasks=311` depois.

### 7.3 Bancos em quarentena - revisar e decidir

| Pasta | Tamanho | Conteudo |
| --- | --- | --- |
| `C:\data\_quarentena-julho-2026\` | 303 KB | Banco de 10-13/07, origem desconhecida |
| `C:\data\_quarentena-importado-legado\` | 311 KB | Importado do legado em 21/09, 78 obrigacoes de julho |

**Acao pendente:** conferir se alguem digitou algo no segundo banco entre
16:49 e 17:00 de 21/09 (janela em que ele serviu a aplicacao). Se sim, esses
lancamentos precisam ser refeitos a mao - eles nao estao no banco atual.

### 7.4 Outros

- [ ] Backup `C:\backups-deploy\20260921-1643` copiado para fora da VM?
- [ ] Commitar `backup_direto.py` no repositorio, para nao depender de copia manual
- [ ] Agendar `backup_direto.py` diario no Task Scheduler (roda com o servico no ar)
- [ ] Avaliar remover a tarefa agendada `GerenciadoContabil` de vez
- [ ] Avaliar remover a venv orfa `.venv`
- [ ] Windows nao ativado ("Activate Windows" no desktop)
- [ ] pip desatualizado no venv (24.3.1 -> 26.2.1), sem urgencia

---

## 8. Ferramentas criadas neste deploy

### `C:\deploy-tools\backup_direto.py`

Backup validado via API do SQLite (`sqlite3.Connection.backup`). Funciona com
o servico no ar. Imprime `integrity_check` da origem e do destino, contagens
comparadas das 4 tabelas, e `BACKUP_OK` ou `BACKUP INVALIDO`.

```powershell
.\venv\Scripts\python.exe "C:\deploy-tools\backup_direto.py" <origem.db> <destino.db>
```

### `C:\deploy-tools\cmp.py`

Compara contagens de dois bancos. Recebe os caminhos como argumentos.

```powershell
.\venv\Scripts\python.exe "C:\deploy-tools\cmp.py" <banco_a.db> <banco_b.db>
```

### `C:\deploy-tools\task.xml`

Export do XML da tarefa agendada `GerenciadoContabil`, caso precise recriar.

---

## 9. Conteudo de `scripts\` (pos-pull)

Do repositorio, 15/07: `backup_app_db.py`, `backup_legacy_sqlite.py`,
`check_project.py`, `export_legacy_sqlite.py`, `import_legacy_data.py`,
`legacy_schema_smoke_test.py`, `smoke_test.py`, `start_production.ps1`,
`verify_counts.py`

Novos no commit `fc88708`: `criar_usuario.py`, `smoke_test.py` (atualizado)

**Atencao:** `start_production.ps1` sobe a aplicacao manualmente. Nao use - o
servico NSSM e o caminho oficial, e rodar os dois cria disputa pela porta 8000.

### Criar usuario

```powershell
cd "C:\Gerenciado Contabil"
$env:DATABASE_URL = "sqlite:///C:/data/gerenciado-contabil/controle_contabil.db"
.\venv\Scripts\python.exe scripts\criar_usuario.py --id <id> --nome "<Nome>" --perfil gerente --senha "<provisoria>"
```

Entregue a senha pessoalmente. O primeiro login exige a troca
(`must_change_password`).

---

## 10. Cola rapida

```powershell
# estado
Get-Service TaskManagerPython | Select-Object Name, Status, StartType
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue

# parar / subir
Stop-Service  -Name "TaskManagerPython" -Force
Start-Service -Name "TaskManagerPython"

# contagens
.\venv\Scripts\python.exe "C:\deploy-tools\cmp.py" "C:\data\gerenciado-contabil\controle_contabil.db" "C:\data\gerenciado-contabil\controle_contabil.db"

# logs do NSSM (se configurados)
C:\Tools\NSSM\nssm.exe get TaskManagerPython AppStdout
C:\Tools\NSSM\nssm.exe get TaskManagerPython AppStderr
```

| Referencia | Valor |
| --- | --- |
| Servico | `TaskManagerPython` |
| Banco | `C:\data\gerenciado-contabil\controle_contabil.db` |
| Commit deste deploy | `fc887088a45a9ed87857c7087be9090c6e8f80c2` |
| Commit anterior | `153c2d07544cf130cf44ef6181bdfe4b592b5384` |
| Backup | `C:\backups-deploy\20260921-1643\PRODUCAO-final.db` |
| Contagens de referencia | 6 users / 311 tasks / 997 subtasks / 5 chamados |
| URL | `http://srvapp01:8000/` |
