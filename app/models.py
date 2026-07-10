from sqlalchemy import Boolean, Column, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    senha = Column(String, nullable=False)
    perfil = Column(String, nullable=False)
    categoria = Column(String, nullable=True)
    cor = Column(String, default="#1e3a5f", nullable=False)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    legacy_data = Column("data", Text, nullable=False, default="{}", server_default="{}")
    legacy_id = Column(String, nullable=True, index=True)
    titulo = Column(String, nullable=False)
    categoria = Column(String, nullable=False)
    tipo = Column(String, default="rotina", nullable=False)
    prioridade = Column(String, default="normal", nullable=False)
    status = Column(String, default="pendente", nullable=False)
    competencia = Column(String, nullable=False)
    liberacao = Column(Date, nullable=True)
    vencimento = Column(Date, nullable=True)
    data_conclusao = Column(Date, nullable=True)
    cliente = Column(String, nullable=True)
    responsavel = Column(String, nullable=True)
    obs = Column(String, nullable=True)
    created_at = Column(Date, nullable=True)
    legacy_raw = Column(Text, nullable=True)

    subtarefas = relationship(
        "Subtask",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="Subtask.id",
    )


class Subtask(Base):
    __tablename__ = "subtasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    legacy_id = Column(String, nullable=True, index=True)
    titulo = Column(String, nullable=False)
    responsavel = Column(String, nullable=True)
    concluida = Column(Boolean, default=False, nullable=False)
    liberacao = Column(String, nullable=True)
    vencimento = Column(Date, nullable=True)
    data_conclusao = Column(String, nullable=True)

    task = relationship("Task", back_populates="subtarefas")


class AppMetadata(Base):
    __tablename__ = "app_metadata"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)
