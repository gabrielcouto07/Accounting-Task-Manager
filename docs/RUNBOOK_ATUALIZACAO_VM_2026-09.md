# Runbook - Atualizacao da VM srvapp01 (setembro/2026)

Procedimento para levar o commit `fc88708` (ja no GitHub) para a VM
`C:\Gerenciado Contabil`, sem perder nenhum dado.

Este runbook e especifico para a instalacao real da VM:

| Item | Valor real hoje |
| --- | --- |
| Pasta do codigo | `C:\Gerenciado Contabil` (e um clone git) |
| Banco de producao | `C:\Gerenciado Contabil\controle_contabil.db` (+ `-wal` de ~4 MB) |
| Python do servico | `C:\Gerenciado Contabil\venv\Scripts\python.exe` |
| Servico | Tarefa agendada `GerenciadoContabil`, roda como SYSTEM, porta 8000 |
| Configuracao | `C:\Gerenciado Contabil\.env` |

Ao final, o banco estara em `C:\data\gerenciado-contabil\` - fora da pasta do
codigo - e as proximas atualizacoes deixam de ter qualquer risco para os dados.

---

## 1. Por que isto e seguro (fatos conferidos no repositorio)

- **Nenhum arquivo `.db`, `.db-wal`, `.db-shm`, `.env` ou `.session_secret`
  esta no git, e nunca esteve em commit nenhum.** Um `git pull` nao consegue
  sobrescrever nem apagar o banco nem a configuracao da VM.
- **A atualizacao nao apaga nenhum arquivo.** `git diff --diff-filter=D` do
  primeiro commit ate `fc88708` retorna vazio: so ha arquivos novos e
  alterados.
- **As mudancas no banco sao apenas aditivas**, aplicadas sozinhas no primeiro
  start (`crud.ensure_schema`):
  - `users.must_change_password` - coluna nova, `NOT NULL DEFAULT 0`. Quem ja
    usa o sistema continua entrando normalmente.
  - `tasks.solicitante` - coluna nova, aceita nulo. Tarefas antigas ficam sem
    solicitante.
  - Indices `ix_tasks_*` e `ix_subtasks_task_id` - criados com
    `IF NOT EXISTS`. Nao alteram dado.
  - Nenhum `DROP`, nenhum `DELETE`, nenhuma reescrita de linha existente.
- **`DATABASE_URL` e respeitado por todas as versoes do codigo**, inclusive o
  commit inicial. Mover o banco nao quebra um eventual rollback.

### O unico passo sem volta

Na primeira inicializacao, `upgrade_plaintext_passwords` converte senhas
gravadas em texto puro para hash PBKDF2. **A senha das pessoas nao muda** -
muda so como ela fica guardada no arquivo. O que nao volta e o valor literal
da senha aparecendo no `.db`. Se voce precisa ler alguma senha antiga, leia
**antes** da atualizacao (o preflight informa quantas ainda estao em texto
puro).

### O risco de verdade nao e o codigo, e o `-wal`

O arquivo `controle_contabil.db-wal` tem ~4 MB contra 396 KB do `.db`: **a
maior parte do que foi digitado recentemente esta no `-wal`, nao no `.db`**.
Copiar so o `controle_contabil.db` para o Desktop nao e backup - perde tudo
que esta no WAL. Por isso o backup abaixo ou copia os tres arquivos juntos,
ou usa a API de backup do proprio SQLite.

---

## 2. Antes de comecar

- [ ] Avisar a equipe: o sistema fica fora do ar por ~15 minutos.
- [ ] Fazer fora do horario de uso.
- [ ] Ter onde gravar o backup **fora da VM** (pendrive, share de rede, outro
      servidor). Backup que mora so na VM nao protege contra a VM.
- [ ] Abrir o PowerShell **como Administrador** na VM.

### Copiar os dois scripts auxiliares para a VM

Estes dois arquivos ainda nao estao no GitHub (decisao sua), entao copie-os
da sua maquina para a VM antes de comecar - por RDP (copiar/colar) ou
`\\srvapp01\c$\Gerenciado Contabil\scripts\`:

| Origem (sua maquina) | Destino (VM) |
| --- | --- |
| `scripts\preflight_vm.py` | `C:\Gerenciado Contabil\scripts\preflight_vm.py` |
| `scripts\backup_app_db.py` | `C:\Gerenciado Contabil\scripts\backup_app_db_v2.py` |

O segundo vai com **nome diferente** de proposito: assim ele fica como arquivo
novo (nao rastreado) e o `git pull` do passo 7 nao da conflito com a versao
antiga que esta no repositorio.

---

## 3. Fase 1 - Diagnostico (servico no ar, nao escreve nada)

```powershell
cd "C:\Gerenciado Contabil"
Get-Content .env                      # ver se ja existe DATABASE_URL aqui
.\venv\Scripts\python.exe scripts\preflight_vm.py
```

Anote da saida:

- `caminho=` - confirme que e o banco usado de verdade (o `.db` cujo `-wal`
  tem data de hoje).
- `users=`, `tasks=`, `subtasks=`, `chamados=` - **anote estes numeros.**
  Sao eles que voce vai conferir no final.
- `integrity_check=ok` - se vier diferente de `ok`, **pare aqui** e resolva a
  corrupcao antes de qualquer coisa.
- `senhas_em_texto_puro=` - quantas serao convertidas para hash.
- `python=` - precisa ser 3.11 ou maior.
- `alteracoes_locais=` - se houver alteracao feita direto na VM, decida o que
  fazer com ela antes do pull (fase 5).

E esperado nesta fase o aviso `banco_dentro_do_codigo=SIM` - e exatamente isso
que a fase 4 corrige.

---

## 4. Fase 2 - Parar o servico

```powershell
Stop-ScheduledTask -TaskName "GerenciadoContabil"

# confirmar que ninguem esta mais escrevendo no banco
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force }
Start-Sleep -Seconds 3
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
```

O ultimo comando tem que nao retornar nada. **So siga quando a porta 8000
estiver livre** - backup com o servico escrevendo e backup pela metade.

---

## 5. Fase 3 - Backup (nao pule, nao resuma)

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$dest  = "C:\backups-deploy\$stamp"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# 5.1 - copia integral da pasta (codigo + .env + banco + wal + .git)
robocopy "C:\Gerenciado Contabil" "$dest\pasta" /E /XD venv .venv __pycache__ /R:1 /W:1

# 5.2 - backup consolidado do banco em UM arquivo, ja verificado
cd "C:\Gerenciado Contabil"
$env:DATABASE_URL = "sqlite:///C:/Gerenciado Contabil/controle_contabil.db"
.\venv\Scripts\python.exe scripts\backup_app_db_v2.py --out "$dest"
```

O `robocopy` termina com codigo 1 quando copiou arquivos - isso e **sucesso**,
nao erro (so 8 ou mais e falha).

O script 5.2 tem que imprimir `integrity_check=ok`, as contagens das tabelas e
`backup_ok=...`. **Confira que as contagens batem com as da fase 1.** Se
imprimir `BACKUP INVALIDO`, pare tudo.

```powershell
# 5.3 - levar o backup para FORA da VM
Get-ChildItem $dest -Recurse | Measure-Object -Property Length -Sum
```

Copie a pasta `$dest` para outra maquina agora. Confirme que chegou inteira
antes de seguir.

---

## 6. Fase 4 - Mover o banco para fora da pasta do codigo

Com o servico **parado** (fase 2).

```powershell
New-Item -ItemType Directory -Force -Path "C:\data\gerenciado-contabil" | Out-Null

# consolida o -wal dentro do .db e remove -wal/-shm
.\venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect(r'C:\Gerenciado Contabil\controle_contabil.db'); c.execute('PRAGMA journal_mode=DELETE'); c.commit(); c.close()"

Get-ChildItem "C:\Gerenciado Contabil\controle_contabil.db*"
```

**Ponto de atencao:** o `Get-ChildItem` acima tem que listar **somente**
`controle_contabil.db`. Se ainda sobrar `-wal` ou `-shm`, alguem ainda esta
com o banco aberto: volte a fase 2 e nao mova nada. Mover o `.db` deixando um
`-wal` para tras perde dados.

```powershell
Move-Item "C:\Gerenciado Contabil\controle_contabil.db" "C:\data\gerenciado-contabil\controle_contabil.db"

# apontar a aplicacao para o novo caminho, em dois lugares (cinto e suspensorio)
[Environment]::SetEnvironmentVariable("DATABASE_URL","sqlite:///C:/data/gerenciado-contabil/controle_contabil.db","Machine")
Add-Content "C:\Gerenciado Contabil\.env" "DATABASE_URL=sqlite:///C:/data/gerenciado-contabil/controle_contabil.db"
```

A variavel de maquina existe porque o servico roda como SYSTEM e a leitura do
`.env` so passou a existir a partir do commit `153c2d0`. Com a variavel de
maquina definida, ate uma versao antiga do codigo encontra o banco no lugar
certo.

Confira que a linha `DATABASE_URL` nao ficou duplicada nem conflitante:

```powershell
Get-Content "C:\Gerenciado Contabil\.env" | Select-String "DATABASE_URL"
```

Nao apague `C:\Gerenciado Contabil\app\controle.db` - e o banco legado do
sistema antigo. Ele so e lido se a tabela `tasks` estiver vazia; com dados em
producao, ninguem encosta nele.

---

## 7. Fase 5 - Atualizar o codigo

```powershell
cd "C:\Gerenciado Contabil"

# ANOTE este commit: e para ele que o rollback volta
git log -1 --pretty="%H %s"

git status --porcelain
```

Se `git status` mostrar algo, decida antes de continuar:
`git stash push -m "ajustes feitos na vm"` guarda as alteracoes, e
`git stash pop` devolve depois.

```powershell
git fetch origin
git log --oneline HEAD..origin/main        # o que vai entrar
git pull --ff-only origin main
git log -1 --pretty="%H %s"                # deve terminar em fc88708

.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

O `--ff-only` e proposital: se o historico tiver divergido, o pull falha em
vez de criar um merge inesperado no servidor.

---

## 8. Fase 6 - Subir e conferir

```powershell
Start-ScheduledTask -TaskName "GerenciadoContabil"
Start-Sleep -Seconds 10
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object LocalAddress, OwningProcess
Invoke-RestMethod http://localhost:8000/health
```

### Conferencia 1 - o banco certo esta sendo usado

```powershell
Get-ChildItem "C:\data\gerenciado-contabil\"
Get-ChildItem "C:\Gerenciado Contabil\controle_contabil.db*" -ErrorAction SilentlyContinue
```

- Em `C:\data\gerenciado-contabil\` tem que aparecer o `.db` **e** um `-wal`
  novo: prova de que a aplicacao esta escrevendo la.
- Em `C:\Gerenciado Contabil\` **nao pode** ter aparecido nenhum
  `controle_contabil.db`. Se apareceu, o `DATABASE_URL` nao pegou: pare o
  servico, apague o arquivo novo (ele e vazio/demo), corrija a variavel e suba
  de novo.

### Conferencia 2 - os dados continuam la

```powershell
$env:DATABASE_URL = "sqlite:///C:/data/gerenciado-contabil/controle_contabil.db"
.\venv\Scripts\python.exe scripts\preflight_vm.py
```

Esperado agora:

- `banco_dentro_do_codigo=nao`
- `colunas_a_criar=0` (as duas colunas novas ja existem)
- `users=`, `tasks=`, `subtasks=`, `chamados=` **iguais** aos da fase 1
- `senhas_em_texto_puro=0`

### Conferencia 3 - o sistema em si

- [ ] `http://IP_DA_VM:8000/login` abre de outro PC.
- [ ] Um usuario existente entra com a senha de sempre.
- [ ] O dashboard mostra as tarefas de sempre.
- [ ] Uma tarefa antiga aparece sem solicitante (esperado).
- [ ] Criar uma tarefa extraordinaria de teste e conferir o e-mail.
- [ ] Abrir um chamado de teste e conferir o e-mail.

### Fase 7 - usuaria da diretoria (se for o caso)

```powershell
cd "C:\Gerenciado Contabil"
$env:DATABASE_URL = "sqlite:///C:/data/gerenciado-contabil/controle_contabil.db"
.\venv\Scripts\python.exe scripts\criar_usuario.py --id sirlandia --nome "Sirlandia" --perfil gerente --senha "<senha-provisoria-forte>"
```

Entregue a senha provisoria pessoalmente. No primeiro login o sistema exige a
troca.

---

## 9. Rollback

### Caso A - subiu, mas algo no codigo esta errado (dados intactos)

```powershell
Stop-ScheduledTask -TaskName "GerenciadoContabil"
cd "C:\Gerenciado Contabil"
git reset --hard COMMIT_ANOTADO_NA_FASE_5
Start-ScheduledTask -TaskName "GerenciadoContabil"
```

As duas colunas novas continuam no banco e sao simplesmente ignoradas pela
versao antiga. O `DATABASE_URL` de maquina continua valendo, entao a versao
antiga encontra o banco em `C:\data\`.

### Caso B - precisa voltar tambem os dados

```powershell
Stop-ScheduledTask -TaskName "GerenciadoContabil"
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force }

Remove-Item "C:\data\gerenciado-contabil\controle_contabil.db-wal" -ErrorAction SilentlyContinue
Remove-Item "C:\data\gerenciado-contabil\controle_contabil.db-shm" -ErrorAction SilentlyContinue
# o arquivo da fase 5.2 tem o nome no formato 20260921-153519.controle_contabil.db
Copy-Item "C:\backups-deploy\STAMP\AAAAMMDD-HHMMSS.controle_contabil.db" "C:\data\gerenciado-contabil\controle_contabil.db" -Force

Start-ScheduledTask -TaskName "GerenciadoContabil"
```

Apagar o `-wal`/`-shm` antigos e obrigatorio: se ficarem ao lado de um `.db`
restaurado, o SQLite tenta aplicar um WAL que nao pertence aquele arquivo.

Tudo que foi digitado entre o backup e o rollback se perde - por isso a janela
de manutencao com o sistema fora do ar.

### Caso C - desastre total na VM

A copia `\pasta` da fase 5.1 tem codigo, `.env`, `.git` e banco. Restaurar a
pasta, recriar a venv (`python -m venv venv` +
`venv\Scripts\python.exe -m pip install -r requirements.txt`) e recriar a
tarefa agendada reconstroi o ambiente inteiro.

---

## 10. Depois deste deploy

- O banco esta fora da pasta do codigo. As proximas atualizacoes viram:
  parar servico -> backup -> `git pull` -> `pip install -r requirements.txt`
  -> subir -> conferir.
- Vale agendar o `scripts\backup_app_db_v2.py` no Task Scheduler, diario. Ele
  roda com o servico no ar (usa a API de backup do SQLite) e ja valida o
  resultado.
- Vale tambem commitar `preflight_vm.py` e a versao nova de
  `backup_app_db.py`, para que a VM receba os dois por `git pull` da proxima
  vez, em vez de copia manual.
