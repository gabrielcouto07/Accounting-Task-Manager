# Atualização de Setembro/2026 — explicada linha a linha

> Documento de estudo. A ideia aqui não é só listar o que mudou, e sim explicar
> **a sintaxe** usada, **por que** ela foi escolhida e **como** cada pedaço
> funciona. Leia com o código aberto do lado.

**Índice**

1. [Panorama do que foi feito](#1-panorama-do-que-foi-feito)
2. [Auditoria: os problemas que existiam](#2-auditoria-os-problemas-que-existiam)
3. [Feature A — usuária Sirlândia](#3-feature-a--usuária-sirlândia)
4. [Feature B — troca de senha no primeiro acesso](#4-feature-b--troca-de-senha-no-primeiro-acesso)
5. [Feature C — filtro por responsável e solicitante](#5-feature-c--filtro-por-responsável-e-solicitante)
6. [Sintaxe explicada (a parte de estudo)](#6-sintaxe-explicada-a-parte-de-estudo)
7. [Como subir na VM sem perder dados](#7-como-subir-na-vm-sem-perder-dados)
8. [O que eu NÃO mexi e por quê](#8-o-que-eu-não-mexi-e-por-quê)
9. [Glossário](#9-glossário)

---

## 1. Panorama do que foi feito

Arquivos alterados:

| Arquivo | O que mudou |
| --- | --- |
| `app/models.py` | 2 colunas novas: `users.must_change_password`, `tasks.solicitante` |
| `app/crud.py` | Migração automática das colunas, filtros novos, conversão de senhas |
| `app/logic.py` | Competências deixaram de ser fixas em 2026; `group_tasks` reescrita |
| `app/auth.py` | Nova dependência `get_active_user` (trava quem tem senha provisória) |
| `app/main.py` | Chave de sessão segura, rotas `/trocar-senha`, filtros no dashboard |
| `app/static/app.js` | Correção de XSS, filtros novos |
| `app/static/style.css` | 6 linhas: botão "Minha senha" e a tarja de filtro ativo |
| `app/templates/*` | 2 selects no dashboard, 1 botão no cabeçalho, tela nova de senha |
| `scripts/criar_usuario.py` | **Novo.** Cria usuário direto no banco |
| `scripts/smoke_test.py` | +85 linhas de teste cobrindo tudo que foi adicionado |
| `.env.example` | **Novo.** Modelo de configuração |
| `docs/deployment_vm_lan.md` | Procedimento de atualização desta versão |

O visual continua idêntico. As únicas coisas novas na tela são: dois `<select>`
dentro da caixa de filtros que já existia, um botão "Minha senha" no cabeçalho
(usando exatamente o mesmo estilo do "Sair"), uma linha "Solicitante:" no card
da tarefa e uma tela de troca de senha que reaproveita o CSS da tela de login.

---

## 2. Auditoria: os problemas que existiam

### 2.1 🔴 Senhas gravadas em texto puro no banco

**O que eu achei.** Rodando um `SELECT` no `controle_contabil.db`:

```
('gerente',         'Gerente',         'gerente',  ..., 'gerente123')
('rafael.pinheiro', 'Rafael Pinheiro', 'gerente',  ..., 'Galo@#1313')
```

A senha estava legível no arquivo. O sistema até tinha a correção certa em
`app/security.py` (PBKDF2 com 310.000 iterações), e o login fazia o *upgrade*
quando a pessoa entrava — mas quem nunca entrou ficava com a senha exposta
para sempre. Como o `.db` fica numa pasta de rede da VM, qualquer pessoa com
acesso ao arquivo lia as senhas.

**Como resolvi.** Uma função que roda uma vez na inicialização:

```python
def upgrade_plaintext_passwords(db: Session) -> int:
    convertidos = 0
    for user in db.query(models.User).all():
        if security.is_hashed_password(user.senha):
            continue                                    # já está em hash, pula
        user.senha = security.hash_password(user.senha or "")
        convertidos += 1
    if convertidos:
        db.flush()
    return convertidos
```

**Por que assim.** Repare no `continue`: ele evita re-hashear um hash (isso
quebraria o login de todo mundo). E o ponto mais importante: **a senha da
pessoa não muda**. `hash_password("Galo@#1313")` guarda uma impressão digital
irreversível dessa senha; o Rafael continua digitando `Galo@#1313` e entrando.
O que sai do arquivo é o texto legível.

Testei isso numa cópia do banco real: as 6 senhas foram convertidas e o login
com a senha antiga continuou funcionando.

### 2.2 🔴 Chave de sessão fixa dentro do código

```python
# ANTES
secret_key=os.getenv("SESSION_SECRET_KEY", "troque-esta-chave-em-producao")
```

`os.getenv(chave, padrao)` devolve o valor da variável de ambiente **ou** o
segundo argumento se ela não existir. O problema: se ninguém definisse a
variável na VM (e o guia dizia "replace-with...", ou seja, dependia de alguém
lembrar), o sistema rodava com uma senha que está escrita em texto no
GitHub. Quem conhece esse texto consegue **fabricar um cookie de sessão** e
entrar como gerente sem senha nenhuma.

```python
# DEPOIS (resumido)
def _session_secret() -> str:
    env_secret = os.getenv("SESSION_SECRET_KEY", "").strip()
    if env_secret:
        return env_secret

    key_file = Path(os.getenv("SESSION_SECRET_FILE", str(ROOT_DIR / ".session_secret")))
    if key_file.exists():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    generated = secrets.token_urlsafe(48)
    key_file.write_text(generated, encoding="utf-8")
    return generated
```

**Sintaxe interessante aqui:**

- `os.getenv("SESSION_SECRET_KEY", "").strip()` — o padrão virou string vazia.
  `"".strip()` é `""`, e `if env_secret:` é **falso** para string vazia. Em
  Python, `""`, `0`, `[]`, `{}` e `None` são todos "falsy". Isso evita o bug
  clássico de alguém setar `SESSION_SECRET_KEY=` (vazia) e o sistema aceitar.
- `secrets.token_urlsafe(48)` — módulo `secrets`, não `random`. O `random` é
  previsível (bom para sorteio de jogo, péssimo para criptografia); `secrets`
  usa a fonte de aleatoriedade do sistema operacional.
- Guardar em arquivo (`.session_secret`, já no `.gitignore`) faz as sessões
  sobreviverem a um restart. Se fosse só `secrets.token_urlsafe()` em memória,
  todo reinício do serviço deslogaria a equipe inteira.

Também adicionei `max_age` (12h) e `https_only` configurável no
`SessionMiddleware`.

### 2.3 🔴 O sistema quebraria em 01/01/2027

```python
# ANTES — app/logic.py
COMPETENCIAS = ["Jan/26", "Fev/26", ..., "Dez/26"]

def competencia_atual() -> str:
    hoje = date.today()
    comp = f"{MESES_ABREV[hoje.month - 1]}/{hoje.strftime('%y')}"
    return comp if comp in COMPETENCIAS else COMPETENCIAS[-1]
```

Em janeiro de 2027, `comp` seria `"Jan/27"`, que **não está** na lista. O
`else COMPETENCIAS[-1]` devolveria `"Dez/26"` — o dashboard abriria travado em
dezembro de 2026 e não haveria como cadastrar nada em 2027, porque o
`<select>` de competência é montado a partir dessa mesma lista.

Havia um segundo bug junto:

```python
def next_comp(competencia: str) -> str:
    index = COMPETENCIAS.index(competencia)
    return COMPETENCIAS[(index + 1) % len(COMPETENCIAS)]   # ⚠️
```

O `%` (módulo) faz a lista dar a volta: `Dez/26` → índice 11 → `(11+1) % 12`
→ `0` → `Jan/26`. Ou seja, replicar uma obrigação de dezembro jogava ela um
ano **para trás**.

**Como resolvi.** Troquei constante por cálculo:

```python
def parse_competencia(competencia: str | None) -> tuple[int, int] | None:
    """'Jun/26' -> (2026, 6). Retorna None se o texto não for reconhecido."""
    if not competencia or "/" not in competencia:
        return None
    mes_txt, _, ano_txt = competencia.partition("/")
    ...
    return ano, MESES_ABREV.index(mes_txt) + 1


def next_comp(competencia: str) -> str:
    parsed = parse_competencia(competencia)
    if not parsed:
        return competencia_atual()
    ano, mes = parsed
    return format_competencia(ano + 1, 1) if mes == 12 else format_competencia(ano, mes + 1)
```

**Sintaxe explicada:**

| Trecho | O que é |
| --- | --- |
| `str \| None` | "string **ou** None". Substitui o antigo `Optional[str]`. É só documentação para o editor — o Python não obriga nada em tempo de execução. |
| `tuple[int, int]` | Uma tupla de exatamente dois inteiros. Serve para o VS Code te avisar se você tentar `parsed[2]`. |
| `"Jun/26".partition("/")` | Devolve **três** partes: `("Jun", "/", "26")`. Diferente do `split("/")`, que devolveria duas e quebraria se houvesse duas barras. |
| `mes_txt, _, ano_txt = ...` | *Unpacking*: distribui a tupla em três variáveis de uma vez. O `_` é convenção para "esse valor eu não vou usar" (é o separador `/`). |
| `A if cond else B` | Operador ternário. Lê-se: "devolva A **se** cond, **senão** B". É uma expressão, então pode ir direto no `return`. |

E a lista virou uma janela rolante calculada na hora:

```python
def competencias_padrao(hoje: date | None = None) -> list[str]:
    hoje = hoje or date.today()
    anos = range(hoje.year - COMP_ANOS_ATRAS, hoje.year + COMP_ANOS_FRENTE + 1)
    return [format_competencia(ano, mes) for ano in anos for mes in range(1, 13)]
```

- `hoje = hoje or date.today()` — se `hoje` for `None` (falsy), usa hoje. É o
  jeito curto de escrever `if hoje is None: hoje = date.today()`.
  ⚠️ Cuidado: esse truque falha quando o valor válido pode ser falsy (ex.: `0`).
- O `return` é uma **list comprehension com dois `for`**. Ela equivale a:

```python
resultado = []
for ano in anos:
    for mes in range(1, 13):
        resultado.append(format_competencia(ano, mes))
return resultado
```

  A ordem dos `for` na comprehension é a mesma do laço aninhado — de fora
  para dentro. É o erro mais comum quando se aprende essa sintaxe.

E o `montar_competencias` junta a janela padrão com o que já existe no banco,
para nunca esconder uma competência antiga que alguém cadastrou:

```python
def montar_competencias(existentes: Iterable[str] | None = None) -> list[str]:
    valores = set(competencias_padrao())
    valores.update(comp for comp in (existentes or []) if comp)
    return sorted(valores, key=comp_sort_key)
```

- `set(...)` — conjunto: não guarda duplicatas. Se `Jun/26` vier do banco e da
  janela padrão, aparece uma vez só.
- `comp for comp in (...) if comp` — *generator expression* (sem colchetes).
  Produz os itens sob demanda, sem montar uma lista intermediária na memória.
- `sorted(valores, key=comp_sort_key)` — o `key=` recebe **a função**, sem
  parênteses. O Python chama `comp_sort_key(item)` para cada item e ordena
  pelo resultado. Como `comp_sort_key("Jun/26")` devolve `(2026, 6, "")`, a
  ordenação fica cronológica e não alfabética (que colocaria "Ago" antes de
  "Jan").

### 2.4 🟠 XSS armazenado no formulário de subtarefas

No `app.js`:

```javascript
// ANTES
item.innerHTML = `
  <div class="st-check-preview"></div>
  <span>${subtask.titulo}${resp}${lib}${venc}</span>
  ...
`;
```

`innerHTML` **interpreta o texto como HTML**. Se alguém digitasse
`<img src=x onerror=alert(1)>` como título de subtarefa, o navegador executaria
esse JavaScript. Num sistema interno isso é menos grave, mas é um buraco real:
qualquer pessoa da equipe conseguiria rodar código na tela dos colegas.

```javascript
// DEPOIS
const label = document.createElement('span');
label.textContent = `${subtask.titulo}${resp}${lib}${venc}`;
```

**A regra de ouro:** `textContent` trata tudo como texto; `innerHTML` trata
tudo como HTML. Para dado que veio do usuário, sempre `textContent`.

O mesmo vale para o botão: antes ele usava `onclick="..."` embutido na string
(que precisa de escape correto); agora usa
`remove.addEventListener('click', () => removeSubtaskFromForm(index))`, que
não passa por interpretação de HTML.

> Nos templates Jinja (`.html`) isso já estava seguro: o Jinja liga o
> *autoescape* sozinho para arquivos `.html`, e `{{ t.titulo }}` vira
> `&lt;img...&gt;` automaticamente. O problema era só no JavaScript.

### 2.5 🟡 `group_tasks` com custo quadrático

```python
# ANTES
vencidas = [t for t in tasks if ... and t not in extras]
vencendo = [t for t in tasks if ... and t not in extras and t not in vencidas]
abertas  = [t for t in tasks if ... and t not in extras and t not in vencidas and t not in vencendo]
```

`t not in lista` percorre a lista inteira a cada teste. Com 78 tarefas ninguém
percebe; com 3.000 (o que acontece depois de alguns anos de uso) isso vira
milhões de comparações a cada carregamento de página. Além disso, `in` numa
lista de objetos compara objeto por objeto, o que é frágil.

Reescrevi com **um laço só** e `if/elif`, que por definição coloca cada tarefa
num único grupo:

```python
for task in tasks:
    if task.status == "concluida":
        concluidas.append(task)
        continue
    if task.tipo == "extraordinaria":
        extras.append(task)
        continue

    restante = dias_restantes(task.vencimento)
    if restante is None:
        abertas.append(task)
    elif restante < 0:
        vencidas.append(task)
    elif restante <= 7:
        vencendo.append(task)
    else:
        abertas.append(task)
```

O `continue` pula para a próxima volta do laço. Ele substitui um `else`
gigante e deixa o código "raso" (sem indentação empilhada) — isso se chama
*early return / early continue* e é uma das coisas que mais melhora leitura.

### 2.6 🟡 Outros ajustes menores

- **`LIKE` sem escape.** Buscar por `50%` na caixa de busca fazia o `%` virar
  coringa do SQL e trazer resultados errados. Criei `_escape_like()` e passei
  `escape="\\"` para o SQLAlchemy.
- **Dava para remover o único gerente** e ficar sem ninguém que consegue
  administrar o sistema. Adicionei `count_gerentes()` e um bloqueio.
- **`/health` mentia.** Devolvia `{"ok": true}` mesmo com o banco inacessível.
  Agora roda um `SELECT 1` antes de responder.
- **Sem log configurado.** Adicionei `logging.basicConfig(...)` com data/hora,
  para os erros aparecerem legíveis no console da VM.
- **Cache do navegador.** O `base.html` usa `style.css?v=20260710`. Se você
  sobe CSS/JS novo sem mudar esse número, os navegadores da equipe continuam
  usando o arquivo velho e "a feature não apareceu". Bumpei para `?v=20260921`.
  **Lembre disso toda vez que mexer em `app.js` ou `style.css`.**
- **Índices** em `tasks.competencia`, `tasks.categoria`, `tasks.status` e
  `subtasks.task_id`, criados com `IF NOT EXISTS`.

---

## 3. Feature A — usuária Sirlândia

Você escolheu **perfil gerente, sem criar a categoria "diretoria"**. Na prática:
a Sirlândia enxerga todas as categorias (Fiscal, Contábil, DP, Societário,
Apoio, Cliente), usa as abas do topo e pode administrar usuários e chamados.

> Nota técnica de por que não dá para ter `perfil="gerente"` **e**
> `categoria="diretoria"` ao mesmo tempo sem mexer em mais coisa: o template
> `admin_users.html` faz `categories[u.categoria].label`, e `CATEGORIES` só
> conhece as 6 categorias existentes. Um valor fora dessa lista quebraria a
> tela. Por isso o `crud.create_user` força `categoria=None` para gerentes.

Criei o `scripts/criar_usuario.py` em vez de cadastrar pela tela, porque na VM
você vai precisar rodar isso logo depois do deploy, via PowerShell.

```powershell
$env:DATABASE_URL = "sqlite:///C:/data/gerenciado-contabil/controle_contabil.db"
python scripts\criar_usuario.py --id sirlandia --nome "Sirlandia" --perfil gerente --senha "Diretoria@2026"
```

Saída:

```
criado=sirlandia nome=Sirlandia perfil=gerente categoria=-
senha_provisoria=Diretoria@2026
troca_obrigatoria_no_primeiro_acesso=true
```

### Sintaxe do script

```python
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
```

- `__file__` é o caminho do próprio arquivo `.py`.
- `.resolve()` transforma em caminho absoluto (resolve `..` e links).
- `.parent.parent` sobe dois níveis: `scripts/criar_usuario.py` → `scripts/` →
  raiz do projeto.
- `sys.path.insert(0, ...)` põe a raiz no começo da lista de pastas onde o
  Python procura módulos. **Sem isso**, `from app import crud` falharia quando
  você roda `python scripts/criar_usuario.py` de qualquer lugar.

O `import` do `app` vem **depois** disso, dentro do `main()` — não lá em cima.
Isso é de propósito: `from app.database import engine` já lê `DATABASE_URL` na
hora do import, então ele precisa acontecer depois do `sys.path` estar pronto.

```python
parser.add_argument("--perfil", default="equipe", choices=["gerente", "equipe"])
```

`choices=[...]` faz o `argparse` **recusar** qualquer outro valor com mensagem
de erro automática. Validação de graça.

```python
alfabeto = (string.ascii_letters + string.digits).translate(
    str.maketrans("", "", "lI0O")
)
```

`str.maketrans("", "", "lI0O")` monta uma tabela de tradução onde os três
argumentos são: *de*, *para*, *deletar*. Aqui os dois primeiros são vazios e o
terceiro lista os caracteres a remover — tirando `l`, `I`, `0` e `O` do
alfabeto, porque numa senha provisória lida em voz alta ou por e-mail eles se
confundem.

E o script é **idempotente**: se o usuário já existe, ele avisa e não faz nada
(a menos que você passe `--atualizar-senha`). Rodar duas vezes por engano não
estraga nada.

---

## 4. Feature B — troca de senha no primeiro acesso

### 4.1 A coluna nova

```python
# app/models.py
must_change_password = Column(
    Boolean,
    default=False,
    server_default=text("0"),
    nullable=False,
)
```

Há **dois** defaults e eles são diferentes:

| Parâmetro | Quem aplica | Quando vale |
| --- | --- | --- |
| `default=False` | O Python/SQLAlchemy | Quando você cria um objeto sem passar o campo |
| `server_default=text("0")` | O próprio SQLite | Quando o `ALTER TABLE` adiciona a coluna nas **linhas que já existem** |

O `server_default` é o que garante que os 6 usuários já cadastrados na VM
continuem entrando normalmente, sem serem forçados a trocar a senha. É esse
detalhe que torna a migração segura.

### 4.2 A migração automática

Em `crud.ensure_schema()`:

```python
user_columns = _column_names(db, "users")
if user_columns:
    _ensure_column(
        db, "users", user_columns,
        "must_change_password",
        "must_change_password BOOLEAN NOT NULL DEFAULT 0",
    )
```

E o `_ensure_column`, que já existia no projeto:

```python
def _ensure_column(db, table, columns, name, ddl):
    if name in columns:
        return                                   # já existe, não faz nada
    db.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {ddl}'))
    columns.add(name)
```

**Por que esse padrão importa para você.** SQLite não tem
`ADD COLUMN IF NOT EXISTS`. Então o projeto lê as colunas existentes com
`PRAGMA table_info(...)` e só roda o `ALTER TABLE` se a coluna faltar. O
resultado é uma migração que:

- roda sozinha no `lifespan` (startup da aplicação);
- pode rodar 100 vezes sem efeito colateral;
- **nunca** apaga, renomeia ou reescreve dado existente — `ADD COLUMN` só
  acrescenta.

É por isso que você pode simplesmente trocar a pasta do código na VM e ligar.

### 4.3 A trava (a parte mais importante)

```python
# app/auth.py
def get_active_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    user = get_current_user(request, db)
    if user.must_change_password:
        raise _password_change_exception(request)
    return user
```

E a exceção:

```python
def _password_change_exception(request: Request) -> HTTPException:
    detail = "Troque a senha antes de continuar"
    if request.url.path.startswith("/api/"):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        detail=detail,
        headers={"Location": "/trocar-senha"},
    )
```

**Sintaxe/conceito: o sistema de `Depends` do FastAPI.**

```python
@app.get("/dashboard")
def dashboard_page(
    ...,
    user: models.User = Depends(auth.get_active_user),
):
```

`Depends(f)` diz: "antes de rodar esta função, rode `f` e me entregue o
resultado no parâmetro `user`". O FastAPI resolve isso recursivamente —
`get_active_user` também tem `Depends(get_db)`, então a sessão do banco é
criada, passada, e fechada no fim. Se a dependência levantar uma exceção, a
função da rota **nem chega a rodar**.

É por isso que trocar `Depends(auth.get_current_user)` por
`Depends(auth.get_active_user)` em todas as rotas foi suficiente para travar o
sistema inteiro — não precisei escrever um `if` em cada rota.

A resposta muda conforme o tipo de requisição:
- **Página HTML** → HTTP 303 + cabeçalho `Location: /trocar-senha`. O navegador
  segue o redirecionamento sozinho.
- **Chamada `/api/...`** (feita pelo `fetch` do JavaScript) → HTTP 403 com JSON.
  Redirecionar um `fetch` não adiantaria; o `apiCall()` do `base.html` mostra
  a mensagem num `alert`.

**As duas exceções propositais:** `/trocar-senha` e `/logout` usam
`get_current_user` (só exige estar logado). Se usassem `get_active_user`, a
pessoa seria redirecionada para `/trocar-senha`, que a redirecionaria de novo
para `/trocar-senha`... loop infinito. Isso está comentado no código para você
não "consertar" por engano depois.

### 4.4 Quem é obrigado a trocar

| Situação | `must_change_password` |
| --- | --- |
| Usuários que já existem na VM | `False` — nada muda para eles |
| Usuário criado pela tela `/admin/users` | `True` |
| Usuário criado pela API `/api/users` | `True` |
| Usuário criado pelo `scripts/criar_usuario.py` | `True` (use `--sem-troca-obrigatoria` para desligar) |
| Gerente resetou a senha de **outra** pessoa | `True` |
| Gerente trocou a **própria** senha em `/admin/users` | `False` |
| A pessoa trocou a própria senha em `/trocar-senha` | `False` |

A regra "senha definida por terceiro é sempre provisória" está aqui:

```python
provisoria = target.id != user.id
crud.change_user_password(db, user_id, senha, must_change_password=provisoria)
```

### 4.5 A validação da nova senha

```python
def _validar_nova_senha(senha: str, confirmar: str, senha_atual: str) -> str | None:
    """Retorna a mensagem de erro, ou None se a senha for aceitável."""
    if len(senha) < SENHA_MINIMA:
        return f"A nova senha precisa ter pelo menos {SENHA_MINIMA} caracteres"
    if senha != confirmar:
        return "As senhas nao conferem"
    if senha == senha_atual:
        return "A nova senha precisa ser diferente da atual"
    return None
```

Repare no padrão: a função devolve **`str` quando dá erro e `None` quando está
tudo certo**. Daí o uso fica:

```python
erro = _validar_nova_senha(senha, confirmar_senha, senha_atual)
if erro:
    return _redirect_with_flash(request, "/trocar-senha", erro)
```

Isso é mais limpo do que devolver `(bool, str)` e ter que desempacotar. E o
`f"...{SENHA_MINIMA}..."` é uma **f-string**: o `f` antes das aspas liga a
interpolação, e o que está entre `{}` é avaliado como expressão Python.

O POST ainda confere a senha atual antes de tudo:

```python
if not crud.authenticate_user(db, user_id=user.id, senha=senha_atual):
    return _redirect_with_flash(request, "/trocar-senha", "Senha atual incorreta")
```

Sem isso, alguém que pegasse um computador destravado trocaria a senha do
colega sem saber a antiga.

### 4.6 A tela

`app/templates/change_password.html` reaproveita `#login-screen` e `#login-box`,
os mesmos IDs da tela de login. Zero CSS novo, e visualmente ela "pertence" ao
sistema. O texto muda conforme o contexto:

```jinja
<h2>{% if obrigatorio %}Defina sua senha{% else %}Alterar minha senha{% endif %}</h2>
```

`{% ... %}` é **lógica** no Jinja (if, for, set); `{{ ... }}` é **valor a
imprimir**. Confundir os dois é o erro nº 1 em template.

---

## 5. Feature C — filtro por responsável e solicitante

### 5.1 O problema que os dados já tinham

Antes de escrever o filtro, olhei os valores reais:

```
responsáveis nas tarefas: JAQUELINE, HELLEN, ISABELLE E MARESSA, MARESSA,
                          ISABELLE, '', Isabelle, JOANA, JOA, ANA PAULA,
                          ISABELLE, MARESSA, HELEN
```

O campo "Responsável" é **texto livre**. Existem:
- variações de caixa: `ISABELLE` e `Isabelle`;
- erros de digitação: `HELLEN` / `HELEN`, `JOANA` / `JOA`;
- **nomes combinados**: `ISABELLE E MARESSA`, `ISABELLE, MARESSA`.

Isso muda completamente como o filtro tem que funcionar. Um `WHERE responsavel
= 'ISABELLE'` deixaria de fora as 2 tarefas em que ela divide com a Maressa —
e seria exatamente nesse ponto que alguém diria "o filtro tá errado".

### 5.2 A decisão

```python
def _filtrar_por_pessoa(query, coluna, valor: str, *, contem: bool):
    valor = (valor or "").strip()
    if not valor:
        return query                                     # "Todos" = sem filtro
    if valor == SEM_VALOR:
        return query.filter(or_(coluna.is_(None), coluna == ""))
    padrao = _escape_like(valor)
    alvo = f"%{padrao}%" if contem else padrao
    return query.filter(coluna.ilike(alvo, escape="\\"))
```

| Campo | Modo | Motivo |
| --- | --- | --- |
| **Responsável** | `LIKE %valor%` (contém) | Pega os nomes combinados. Filtrar "ISABELLE" traz também "ISABELLE E MARESSA". |
| **Solicitante** | `LIKE valor` (igual, sem caixa) | Esse campo é preenchido **pelo sistema** com o nome do usuário logado, então é limpo e não precisa de aproximação. |

Resultado medido no banco real: `ISABELLE` → 12 tarefas, `MARESSA` → 13.

**Sintaxe:**

- `def f(query, coluna, valor, *, contem: bool)` — tudo depois do `*` é
  **keyword-only**: você é obrigado a escrever `contem=True`. Sem isso, alguém
  leria `_filtrar_por_pessoa(q, col, "ana", True)` e não faria ideia do que o
  `True` significa.
- `coluna.is_(None)` — em SQLAlchemy você **não** escreve `coluna == None`
  (funciona, mas os linters reclamam e é ambíguo). `is_(None)` gera
  `IS NULL` explicitamente.
- `or_(a, b)` — gera `a OR b` no SQL. Precisa ser função porque o `or` nativo
  do Python avaliaria os objetos como booleanos em vez de montar SQL.
- `.ilike(...)` — `LIKE` insensível a maiúsculas/minúsculas.
- `escape="\\"` — em Python, `"\\"` é **uma** barra invertida. Isso diz ao SQL:
  "quando encontrar `\%`, trate como `%` literal, não como coringa".

### 5.3 Como as opções dos selects são montadas

```python
def _valores_distintos(db, current_user, categoria_tab, coluna) -> list[str]:
    base = db.query(coluna).distinct()
    for condicao in _scope_conditions(current_user, categoria_tab):
        base = base.filter(condicao)
    vistos: dict[str, str] = {}
    for (valor,) in base:
        texto = (valor or "").strip()
        if not texto:
            continue
        vistos.setdefault(texto.casefold(), texto)
    return sorted(vistos.values(), key=str.casefold)
```

Pontos de estudo:

1. **`for (valor,) in base:`** — o parêntese com vírgula desempacota uma tupla
   de **um** elemento. O SQLAlchemy devolve linhas como `("ISABELLE",)`, então
   sem esse desempacotamento `valor` seria a tupla inteira.

2. **`vistos.setdefault(chave, valor)`** — grava só se a chave ainda não existe.
   Usando `texto.casefold()` como chave, `ISABELLE` e `Isabelle` colidem e
   aparece **uma opção só** no select. O `casefold()` é o `lower()` "forte",
   que também trata casos de outros idiomas (ex.: `ß` → `ss`).

3. **`base = base.filter(condicao)` dentro do laço** — queries do SQLAlchemy
   são **imutáveis**: `.filter()` devolve uma query nova em vez de alterar a
   existente. Por isso o reatribuir é obrigatório; só chamar
   `base.filter(...)` sem o `base =` não faria nada.

4. **Escopo.** Extraí `_scope_conditions()` para que a regra "gerente vê tudo,
   equipe vê só a própria categoria" fique escrita **num lugar só** e valha
   tanto para a lista de tarefas quanto para as opções do filtro. Testei: o
   usuário `fiscal` só enxerga responsáveis de tarefas fiscais.

5. **`db.query(coluna)` em vez de reaproveitar `scoped_tasks_query`** — a query
   principal usa `selectinload(Task.subtarefas)`, que carrega as 310 subtarefas.
   Para montar um `<select>` com nomes, isso seria desperdício puro.

### 5.4 A rota

```python
responsavel: str = "",
solicitante: str = "",
```

Declarar assim no parâmetro da função já faz o FastAPI ler
`?responsavel=ISABELLE` da URL, converter para `str` e usar `""` quando não
vier nada. Sem código de parsing manual.

Os KPIs também passaram a respeitar o filtro:

```python
kpi_query = crud.aplicar_filtros_pessoa(
    crud.scoped_tasks_query(db, user, cat_tab),
    responsavel=responsavel,
    solicitante=solicitante,
)
```

**Por quê:** o objetivo do filtro é "ver só a equipe X". Se os cartões de KPI
continuassem mostrando os números da empresa inteira, o filtro entregaria meia
resposta. Sem nada selecionado, o comportamento é **idêntico** ao de antes —
então não há regressão.

### 5.5 O HTML

```jinja
<select id="fil-responsavel" onchange="applyFilters()">
  <option value="" {% if not responsavel %}selected{% endif %}>Todos os responsáveis</option>
  <option value="{{ sem_valor }}" ...>— Sem responsável —</option>
  {% for nome in responsaveis %}
    <option value="{{ nome }}" {% if responsavel == nome %}selected{% endif %}>👤 {{ nome }}</option>
  {% endfor %}
</select>
```

Os dois `<select>` entraram dentro da `.filter-row` que já existia, usando as
mesmas regras de CSS dos outros filtros — por isso não precisei desenhar nada.

### 5.6 O JavaScript

```javascript
function applyFilters() {
  goWithParams({
    categoria:   fieldValue('fil-categoria'),
    tipo:        fieldValue('fil-tipo'),
    prioridade:  fieldValue('fil-prioridade'),
    responsavel: fieldValue('fil-responsavel'),
    solicitante: fieldValue('fil-solicitante'),
    busca:       fieldValue('fil-busca'),
  });
}
```

E a função que já existia no projeto:

```javascript
function withParams(changes) {
  const params = new URLSearchParams(window.location.search);
  Object.entries(changes).forEach(([key, value]) => {
    if (value === null || value === undefined || value === '') {
      params.delete(key);
    } else {
      params.set(key, value);
    }
  });
  return `${window.location.pathname}?${params.toString()}`;
}
```

`Object.entries({a: 1})` vira `[["a", 1]]`, e `([key, value]) => ...` é
**destructuring** no parâmetro do arrow function: a posição 0 do array vira
`key`, a posição 1 vira `value`. O detalhe importante é que valor vazio
**apaga** o parâmetro — por isso escolher "Todos os responsáveis" limpa a URL
em vez de deixar `?responsavel=` pendurado.

Também mudei `setCategoryTab()` para zerar o filtro de pessoa ao trocar de aba:

```javascript
goWithParams({ cat_tab: value, categoria: 'todas', responsavel: '', solicitante: '' });
```

Sem isso, você filtraria por "ISABELLE" na aba Fiscal, clicaria em "DP" e
veria a tela vazia sem entender o motivo, porque a Isabelle não aparece nas
tarefas de DP.

### 5.7 O campo `solicitante`

Você escolheu "solicitante = quem criou a tarefa". Então ele é preenchido
automaticamente, uma vez só:

```python
# app/main.py
task = crud.create_task(db, data, solicitante=user.nome)
```

```python
# app/crud.py
task = models.Task(
    created_at=date.today(),
    legacy_data="{}",
    solicitante=(solicitante or "").strip() or None,
)
```

`(solicitante or "").strip() or None` faz três coisas encadeadas:
1. `solicitante or ""` — se vier `None`, vira `""` (`.strip()` não existe em `None`).
2. `.strip()` — remove espaços das pontas.
3. `... or None` — se sobrou string vazia, grava `None` em vez de `""`. Assim o
   banco tem **um** jeito de representar "sem solicitante", não dois.

**E o `update_task` não mexe nisso de propósito.** O motivo é sutil e vale
entender: o schema `TaskUpdate` herda de `TaskCreate`, que não tem o campo
`solicitante`. Como o `_apply_task_fields()` copia campo a campo a partir do
schema, `task.solicitante` simplesmente nunca é tocado numa edição. Quem criou
continua sendo quem criou, mesmo que outra pessoa edite depois. Testei isso
explicitamente.

Tarefas antigas ficam com `NULL` e aparecem na opção "— Sem solicitante —".

---

## 6. Sintaxe explicada (a parte de estudo)

Resumo dos padrões que aparecem no código, para consulta rápida.

### Python

| Sintaxe | Significa | Exemplo no projeto |
| --- | --- | --- |
| `def f(x: str) -> bool:` | *Type hints*. Só documentação para o editor; o Python não checa em runtime. | `def is_hashed_password(value: str \| None) -> bool` |
| `str \| None` | "str ou None" (Python 3.10+). Antigo `Optional[str]`. | `dash_month: str \| None = None` |
| `list[str]`, `dict[str, str]` | Tipos genéricos embutidos (3.9+). Antes era `List[str]` do `typing`. | `def listar_responsaveis(...) -> list[str]` |
| `def f(a, *, b)` | Tudo após `*` é keyword-only: obrigado a escrever `b=...`. | `_filtrar_por_pessoa(..., *, contem: bool)` |
| `x or y` | Devolve `x` se for *truthy*, senão `y`. | `hoje = hoje or date.today()` |
| `A if cond else B` | Ternário — é expressão, cabe dentro de `return`. | `format_competencia(ano + 1, 1) if mes == 12 else ...` |
| `f"texto {var}"` | f-string: interpola expressões. | `f"%{padrao}%"` |
| `[x for y in z]` | List comprehension. | `[format_competencia(a, m) for a in anos for m in range(1,13)]` |
| `(x for y in z)` | Generator: produz sob demanda, não ocupa memória. | `valores.update(c for c in existentes if c)` |
| `a, _, b = tupla` | Unpacking. `_` = "não vou usar". | `mes_txt, _, ano_txt = comp.partition("/")` |
| `for (x,) in query:` | Unpacking de tupla de 1 elemento. | `for (valor,) in base:` |
| `continue` | Pula para a próxima volta do laço. | `if security.is_hashed_password(...): continue` |
| `d.setdefault(k, v)` | Grava só se a chave não existir. | `vistos.setdefault(texto.casefold(), texto)` |
| `dict.get(k, padrao)` | Lê sem estourar `KeyError`. | `logic.CATEGORIES.get(task.categoria, {})` |
| `sorted(x, key=f)` | Ordena pelo resultado de `f(item)`. `f` vai **sem parênteses**. | `sorted(valores, key=str.casefold)` |
| `set(...)` | Conjunto: sem duplicatas, teste `in` instantâneo. | `valores = set(competencias_padrao())` |
| `@contextmanager` / `with` | Garante limpeza (fechar sessão, rollback). | `with session_scope() as db:` |
| `raise X from exc` | Encadeia exceções preservando a causa original. | `raise HTTPException(...) from exc` |

### FastAPI / SQLAlchemy

| Sintaxe | Significa |
| --- | --- |
| `@app.get("/rota")` | Decorator: registra a função como handler de GET nessa URL |
| `Depends(f)` | Roda `f` antes e injeta o retorno; resolve em cadeia |
| `x: str = Form(...)` | Lê de formulário HTML. O `...` (Ellipsis) significa **obrigatório** |
| `x: str = ""` (na rota) | Lê da *query string* (`?x=...`), com padrão |
| `db.query(M).filter(cond)` | Monta SQL. **Não executa** ainda e devolve query nova (imutável) |
| `.all()` / `.first()` / `.count()` | É aqui que o SQL roda de verdade |
| `col.ilike(p, escape="\\")` | `LIKE` sem diferenciar maiúsculas, com escape de coringas |
| `col.is_(None)` | Gera `IS NULL` |
| `or_(a, b)` | Gera `a OR b` |
| `selectinload(M.rel)` | Carrega o relacionamento numa 2ª query, evitando N+1 |
| `db.flush()` | Manda o SQL, **sem** confirmar. Útil para pegar o ID gerado |
| `db.commit()` | Confirma a transação de verdade |
| `Column(..., server_default=text("0"))` | Default aplicado pelo **banco** — é o que preenche linhas já existentes |

### Jinja (templates)

| Sintaxe | Significa |
| --- | --- |
| `{{ valor }}` | Imprime (com escape de HTML automático) |
| `{% if %}` / `{% for %}` / `{% set %}` | Lógica, não imprime nada |
| `{% include "x.html" %}` | Cola outro template ali, com as mesmas variáveis |
| `{% extends %}` + `{% block %}` | Herança: `base.html` define os buracos, os filhos preenchem |
| `lista\|length`, `x\|tojson` | Filtros. `tojson` converte dado Python em JSON seguro para `<script>` |

### JavaScript

| Sintaxe | Significa |
| --- | --- |
| `` `texto ${var}` `` | Template literal (crase) |
| `el.textContent = x` | Escreve **texto**. Seguro. |
| `el.innerHTML = x` | Escreve **HTML**. Perigoso com dado do usuário. |
| `({a, b}) => ...` / `([k, v]) => ...` | Destructuring no parâmetro |
| `async` / `await` | Espera a promessa resolver sem travar a página |
| `obj?.prop` | Optional chaining: `undefined` em vez de erro se `obj` for nulo |
| `a \|\| b` | `b` quando `a` é falsy (`''`, `0`, `null`, `undefined`) |

---

## 7. Como subir na VM sem perder dados

O procedimento completo está em
[`docs/deployment_vm_lan.md`](deployment_vm_lan.md), seção
"Atualização de Setembro/2026". Resumo:

```powershell
# 1. PARE o serviço

# 2. BACKUP (não pule)
$env:DATABASE_URL = "sqlite:///C:/data/gerenciado-contabil/controle_contabil.db"
cd "C:\apps\gerenciado-contabil"
python scripts\backup_app_db.py

# 3. Substitua a pasta do código (app\, scripts\, docs\, requirements.txt)

# 4. pip install -r requirements.txt

# 5. Suba o serviço. O log deve mostrar:
#    "N senha(s) em texto puro convertida(s) para hash."

# 6. Crie a Sirlândia
python scripts\criar_usuario.py --id sirlandia --nome "Sirlandia" --perfil gerente --senha "Diretoria@2026"

# 7. Confira http://IP_DA_VM:8000/health  ->  {"ok": true, "database": true}
```

**Por que isso é seguro.** A separação código/dados que o guia já recomendava
(`DATABASE_URL` apontando para `C:\data\...`) é o que permite trocar a pasta do
código sem encostar no `.db`. As mudanças de schema são todas
`ALTER TABLE ADD COLUMN` e `CREATE INDEX IF NOT EXISTS` — operações que só
acrescentam.

**Eu testei isso numa cópia do banco real antes de te entregar:**

```
ANTES:  {'users': 6, 'tasks': 78, 'subtasks': 310}
DEPOIS: {'users': 6, 'tasks': 78, 'subtasks': 310}   IGUAL: True
senhas em texto puro restantes: []
must_change dos existentes: todos 0
login com a senha antiga: OK
```

**Antes de subir**, rode sempre na máquina de desenvolvimento:

```powershell
python scripts\check_project.py
```

Ele compila tudo e roda o smoke test — que agora também testa o bloqueio de
senha provisória, a troca de senha, os filtros novos e garante que nenhuma
senha ficou em texto puro.

**Um detalhe operacional:** defina `SESSION_SECRET_KEY` na VM (veja o
`.env.example`). Se não definir, o sistema gera uma chave e grava em
`.session_secret` na pasta do código — que você vai substituir no próximo
deploy, deslogando todo mundo. Não é grave, mas é evitável.

---

## 8. O que eu NÃO mexi e por quê

Coisas que vi e deixei de propósito, para você decidir depois:

1. **A lista de tarefas ignora o mês selecionado.** Os KPIs filtram por
   `dash_month`, mas a lista abaixo mostra todas as competências. Pode ser
   intencional, mas é inconsistente — quem olha os cartões e depois a lista vê
   números que não batem. Mudar isso altera o comportamento que a equipe já
   conhece, então não toquei.

2. **A tela de login lista todos os usuários num `<select>`.** Qualquer pessoa
   que abre a URL descobre todos os logins. Numa rede interna o risco é baixo,
   e trocar por um campo de texto mudaria a cara do login — que você pediu para
   preservar.

3. **Sem proteção CSRF explícita.** O `same_site="lax"` do cookie já barra o
   ataque clássico (o navegador não manda o cookie em POST vindo de outro
   site). Um token CSRF de verdade exigiria mexer em todos os formulários.

4. **`_replace_subtasks` apaga e recria todas as subtarefas** a cada edição da
   tarefa, trocando os IDs. Funciona, mas desperdiça trabalho e impede ter
   histórico por subtarefa no futuro.

5. **`subtasks.data_conclusao` é texto**, guardando ora uma data ISO, ora
   `"NA"`, ora `""`. Normalizar isso exigiria migrar dados existentes — risco
   que não vale a pena neste momento.

6. **Nada de rate limiting no login.** Numa LAN fechada, aceitável.

7. **SQLite.** Com WAL e `busy_timeout` já configurados, aguenta bem uma equipe
   pequena. O caminho de saída (trocar `DATABASE_URL` para PostgreSQL) já está
   documentado.

---

## 9. Glossário

- **Hash (de senha)** — impressão digital irreversível. Dá para conferir se a
  senha digitada bate, mas não dá para descobrir a senha a partir do hash.
- **PBKDF2** — algoritmo que repete o hash 310.000 vezes de propósito, para
  deixar a tentativa de força bruta absurdamente lenta.
- **Salt** — valor aleatório misturado a cada senha, para que duas pessoas com
  a mesma senha tenham hashes diferentes.
- **XSS (Cross-Site Scripting)** — quando texto digitado por um usuário é
  interpretado como código na tela de outro.
- **CSRF** — quando um site malicioso faz o navegador da vítima enviar uma
  requisição autenticada para o seu sistema.
- **Migração** — mudança na estrutura do banco (colunas, tabelas, índices).
- **Idempotente** — rodar uma ou dez vezes dá o mesmo resultado.
- **Dependência (FastAPI)** — função que roda antes da rota e injeta um valor.
- **ORM** — biblioteca que mapeia tabelas em classes Python (aqui, SQLAlchemy).
- **N+1** — fazer 1 query para a lista e mais 1 para cada item. O
  `selectinload` existe para evitar isso.
- **Truthy / falsy** — valores que o `if` trata como verdadeiro/falso. São
  falsy: `False`, `None`, `0`, `""`, `[]`, `{}`.
- **WAL (Write-Ahead Logging)** — modo do SQLite que permite ler enquanto
  alguém escreve.
- **Smoke test** — teste rápido que só verifica se o básico funciona.
