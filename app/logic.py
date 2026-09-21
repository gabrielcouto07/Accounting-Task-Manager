from datetime import date
from typing import Any, Iterable


MESES_ABREV = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

# Quantos anos para tras / para frente a lista de competencias cobre a partir
# do ano corrente. A lista e SEMPRE calculada na hora: antes ela era uma
# constante fixa de 2026 e o sistema quebrava a virada do ano.
COMP_ANOS_ATRAS = 1
COMP_ANOS_FRENTE = 1


def format_competencia(ano: int, mes: int) -> str:
    """(2026, 6) -> 'Jun/26'."""
    return f"{MESES_ABREV[mes - 1]}/{str(ano)[-2:]}"


def parse_competencia(competencia: str | None) -> tuple[int, int] | None:
    """'Jun/26' -> (2026, 6). Retorna None se o texto nao for reconhecido."""
    if not competencia or "/" not in competencia:
        return None
    mes_txt, _, ano_txt = competencia.partition("/")
    mes_txt = mes_txt.strip().capitalize()
    ano_txt = ano_txt.strip()
    if mes_txt not in MESES_ABREV or not ano_txt.isdigit():
        return None
    ano = int(ano_txt)
    if ano < 100:
        ano += 2000
    return ano, MESES_ABREV.index(mes_txt) + 1


def comp_sort_key(competencia: str) -> tuple[int, int, str]:
    """Ordena competencias cronologicamente; valores estranhos vao para o fim."""
    parsed = parse_competencia(competencia)
    if not parsed:
        return (9999, 99, competencia or "")
    return (parsed[0], parsed[1], "")


def competencia_atual() -> str:
    hoje = date.today()
    return format_competencia(hoje.year, hoje.month)


def competencias_padrao(hoje: date | None = None) -> list[str]:
    """Janela rolante de competencias em torno do ano corrente."""
    hoje = hoje or date.today()
    anos = range(hoje.year - COMP_ANOS_ATRAS, hoje.year + COMP_ANOS_FRENTE + 1)
    return [format_competencia(ano, mes) for ano in anos for mes in range(1, 13)]


def montar_competencias(existentes: Iterable[str] | None = None) -> list[str]:
    """Janela padrao + competencias que ja existem no banco, sem duplicar."""
    valores = set(competencias_padrao())
    valores.update(comp for comp in (existentes or []) if comp)
    return sorted(valores, key=comp_sort_key)


# Mantido por compatibilidade com codigo/scripts antigos. Prefira
# `montar_competencias()` (que inclui o que ja existe no banco).
COMPETENCIAS = competencias_padrao()


CATEGORIES = {
    "fiscal": {"label": "Fiscal", "icon": "📋"},
    "contabil": {"label": "Contábil", "icon": "📒"},
    "dp": {"label": "Dep. Pessoal", "icon": "👥"},
    "societario": {"label": "Societário", "icon": "🏛️"},
    "honorarios": {"label": "Apoio Interno", "icon": "🛠️"},
    "cliente": {"label": "Atend. Cliente", "icon": "🤝"},
}

PRIORIDADES = {
    "critica": {"label": "Crítica", "color": "#dc2626", "bg": "#fef2f2"},
    "alta": {"label": "Alta", "color": "#ea580c", "bg": "#fff7ed"},
    "normal": {"label": "Normal", "color": "#2563eb", "bg": "#eff6ff"},
    "baixa": {"label": "Baixa", "color": "#16a34a", "bg": "#f0fdf4"},
}

TIPO_CFG = {
    "rotina": {"label": "Rotina", "color": "#1e3a5f", "bg": "#e0e7ff", "icon": "🔁"},
    "extraordinaria": {
        "label": "Extraordinária",
        "color": "#7c3aed",
        "bg": "#f5f3ff",
        "icon": "⚡",
    },
}

STATUSES = {
    "pendente": {"label": "Pendente", "color": "#6b7280"},
    "em_andamento": {"label": "Em andamento", "color": "#2563eb"},
    "concluida": {"label": "Concluída", "color": "#16a34a"},
}

AVATAR_COLORS = [
    "#1e3a5f",
    "#2563eb",
    "#7c3aed",
    "#16a34a",
    "#ea580c",
    "#dc2626",
    "#0891b2",
]


def dias_restantes(vencimento: date | None) -> int | None:
    if not vencimento:
        return None
    return (vencimento - date.today()).days


def fmt_data(value: date | str | None) -> str:
    if not value:
        return "—"
    if value == "NA":
        return "N/A"
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


def venc_badge(vencimento: date | None, status: str) -> dict[str, str] | None:
    if status == "concluida":
        return None
    restante = dias_restantes(vencimento)
    if restante is None:
        return None
    if restante < 0:
        return {"text": f"Vencido há {abs(restante)}d", "color": "#dc2626", "bg": "#fef2f2"}
    if restante == 0:
        return {"text": "Vence hoje!", "color": "#dc2626", "bg": "#fef2f2"}
    if restante <= 3:
        return {"text": f"Vence em {restante}d", "color": "#ea580c", "bg": "#fff7ed"}
    if restante <= 7:
        return {"text": f"Vence em {restante}d", "color": "#ca8a04", "bg": "#fefce8"}
    return {"text": fmt_data(vencimento), "color": "#6b7280", "bg": "#f3f4f6"}


def pri_order(priority: str) -> int:
    return {"critica": 0, "alta": 1, "normal": 2, "baixa": 3}.get(priority, 9)


def next_comp(competencia: str) -> str:
    """Competencia seguinte. Dez/26 -> Jan/27 (antes voltava para Jan/26)."""
    parsed = parse_competencia(competencia)
    if not parsed:
        return competencia_atual()
    ano, mes = parsed
    return format_competencia(ano + 1, 1) if mes == 12 else format_competencia(ano, mes + 1)


def initials(nome: str) -> str:
    parts = [part for part in nome.split(" ") if part]
    return "".join(part[0] for part in parts[:2]).upper()


def sync_task_status_from_subtasks(task: Any) -> None:
    subtasks = list(task.subtarefas or [])
    if not subtasks:
        return

    done_count = sum(1 for subtask in subtasks if subtask.concluida)
    if done_count == len(subtasks):
        task.status = "concluida"
        if not task.data_conclusao:
            task.data_conclusao = date.today()
        return

    task.data_conclusao = None
    if done_count == 0:
        task.status = "pendente"
    else:
        task.status = "em_andamento"


def sort_tasks(tasks: list[Any]) -> list[Any]:
    def key(task: Any) -> tuple[int, int, str, str]:
        vencimento = task.vencimento.isoformat() if task.vencimento else ""
        return (pri_order(task.prioridade), 1 if not vencimento else 0, vencimento, task.titulo.lower())

    return sorted(tasks, key=key)


def sort_subtasks(subtasks: list[Any]) -> list[Any]:
    def key(subtask: Any) -> tuple[bool, int, str]:
        vencimento = subtask.vencimento.isoformat() if subtask.vencimento else ""
        return (subtask.concluida, 1 if not vencimento else 0, vencimento)

    return sorted(subtasks, key=key)


def build_kpis(tasks: list[Any]) -> list[dict[str, Any]]:
    concluidas = [task for task in tasks if task.status == "concluida"]
    no_prazo = sum(
        1
        for task in concluidas
        if task.data_conclusao and task.vencimento and task.data_conclusao <= task.vencimento
    )
    atraso = sum(
        1
        for task in concluidas
        if task.data_conclusao and task.vencimento and task.data_conclusao > task.vencimento
    )
    vencendo = sum(
        1
        for task in tasks
        if (restante := dias_restantes(task.vencimento)) is not None
        and 0 <= restante <= 3
        and task.status != "concluida"
    )
    vencidos = sum(
        1
        for task in tasks
        if (restante := dias_restantes(task.vencimento)) is not None
        and restante < 0
        and task.status != "concluida"
    )

    return [
        {"label": "Total", "value": len(tasks), "color": "#1e3a5f", "bg": "#fff"},
        {
            "label": "Rotinas",
            "value": sum(1 for task in tasks if task.tipo == "rotina"),
            "color": "#1e3a5f",
            "bg": "#e0e7ff",
        },
        {
            "label": "Extraordinárias",
            "value": sum(1 for task in tasks if task.tipo == "extraordinaria"),
            "color": "#7c3aed",
            "bg": "#f5f3ff",
        },
        {
            "label": "Pendentes",
            "value": sum(1 for task in tasks if task.status == "pendente"),
            "color": "#6b7280",
            "bg": "#fff",
        },
        {
            "label": "Em andamento",
            "value": sum(1 for task in tasks if task.status == "em_andamento"),
            "color": "#2563eb",
            "bg": "#eff6ff",
        },
        {"label": "Concluídas", "value": len(concluidas), "color": "#16a34a", "bg": "#f0fdf4"},
        {"label": "Concluída no prazo", "value": no_prazo, "color": "#16a34a", "bg": "#f0fdf4"},
        {"label": "Concluída em atraso", "value": atraso, "color": "#dc2626", "bg": "#fef2f2"},
        {"label": "Vencendo (3d)", "value": vencendo, "color": "#ea580c", "bg": "#fff7ed"},
        {"label": "Vencidos", "value": vencidos, "color": "#dc2626", "bg": "#fef2f2"},
    ]


def build_category_bars(tasks: list[Any], user: Any, cat_tab: str) -> list[dict[str, Any]]:
    if user.perfil == "gerente" and cat_tab == "todas":
        keys = list(CATEGORIES.keys())
    else:
        keys = [cat_tab if user.perfil == "gerente" else user.categoria]

    bars = []
    for key in keys:
        cat_tasks = [task for task in tasks if task.categoria == key]
        done = sum(1 for task in cat_tasks if task.status == "concluida")
        pct = round((done / len(cat_tasks)) * 100) if cat_tasks else 0
        category = CATEGORIES.get(key, {"label": key, "icon": "📌"})
        bars.append(
            {
                "key": key,
                "icon": category["icon"],
                "label": category["label"],
                "count": len(cat_tasks),
                "pct": pct,
            }
        )
    return bars


def group_extras_by_user(tasks: list[Any]) -> list[tuple[str, list[Any]]]:
    """Agrupa tarefas extraordinárias por responsável (sem responsável por último)."""
    grupos: dict[str, list[Any]] = {}
    for task in tasks:
        nome = (task.responsavel or "").strip() or "Sem responsável"
        grupos.setdefault(nome, []).append(task)
    ordenados = sorted(
        grupos.items(),
        key=lambda item: (item[0] == "Sem responsável", item[0].lower()),
    )
    return [(nome, sort_tasks(itens)) for nome, itens in ordenados]


def group_tasks(tasks: list[Any]) -> list[tuple[str, str, str, list[Any], str]]:
    """Distribui as tarefas nos 5 grupos do dashboard, cada tarefa em um grupo so.

    A versao anterior usava `task not in extras`, que faz busca linear em lista
    (O(n^2) e compara objetos). Aqui cada tarefa passa por um unico `if/elif`.
    """
    extras: list[Any] = []
    vencidas: list[Any] = []
    vencendo: list[Any] = []
    abertas: list[Any] = []
    concluidas: list[Any] = []

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

    return [
        ("extra", "⚡", "Extraordinárias", sort_tasks(extras), "g-extra"),
        ("vencidas", "🔴", "Vencidas", sort_tasks(vencidas), "g-vencidas"),
        ("vencendo", "🟠", "Vencendo em breve", sort_tasks(vencendo), "g-vencendo"),
        ("ativas", "🔵", "Em aberto", sort_tasks(abertas), "g-ativas"),
        ("concluidas", "✅", "Concluídas", sort_tasks(concluidas), "g-concluidas"),
    ]
