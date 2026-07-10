from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    id: str
    nome: str
    senha: str
    perfil: Literal["gerente", "equipe"]
    categoria: Literal["fiscal", "contabil", "dp", "societario", "honorarios", "cliente"] | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nome: str
    perfil: str
    categoria: str | None = None
    cor: str


class SubtaskBase(BaseModel):
    titulo: str
    responsavel: str | None = ""
    concluida: bool = False
    liberacao: str | None = ""
    vencimento: date | None = None
    data_conclusao: str | None = ""


class SubtaskCreate(SubtaskBase):
    pass


class SubtaskOut(SubtaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int


class TaskBase(BaseModel):
    titulo: str
    categoria: Literal["fiscal", "contabil", "dp", "societario", "honorarios", "cliente"]
    tipo: Literal["rotina", "extraordinaria"] = "rotina"
    prioridade: Literal["critica", "alta", "normal", "baixa"] = "normal"
    status: Literal["pendente", "em_andamento", "concluida"] = "pendente"
    competencia: str
    liberacao: date | None = None
    vencimento: date | None = None
    data_conclusao: date | None = None
    cliente: str | None = ""
    responsavel: str | None = ""
    obs: str | None = ""


class TaskCreate(TaskBase):
    subtarefas: list[SubtaskCreate] = Field(default_factory=list)


class TaskUpdate(TaskCreate):
    pass


class TaskOut(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: date | None = None
    subtarefas: list[SubtaskOut] = Field(default_factory=list)


class ReplicateRequest(BaseModel):
    nova_competencia: str
