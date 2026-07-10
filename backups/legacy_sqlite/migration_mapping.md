# Legacy Data Mapping

Generated from the legacy SQLite backup copied from `app/controle.db`.

## Source Tables

- `users`: 6 rows. Maps directly to `app.models.User`.
- `tasks`: 78 rows. Contains `id INTEGER PRIMARY KEY` and `data TEXT NOT NULL`.
- `tasks.data`: JSON payload with the task fields and embedded `subtarefas`.
- Embedded `subtarefas`: 310 total records. Imported into `app.models.Subtask`.

## FastAPI Model Mapping

| Legacy source | FastAPI target | Notes |
| --- | --- | --- |
| `users.id` | `users.id` | Preserved exactly, including `rafael.pinheiro`. |
| `users.nome` | `users.nome` | Preserved exactly. |
| `users.senha` | `users.senha` | Preserved exactly to match legacy login behavior. |
| `users.perfil` | `users.perfil` | `gerente` or `equipe`. |
| `users.categoria` | `users.categoria` | Preserved for equipe users. |
| `users.cor` | `users.cor` | Preserved for avatars. |
| `tasks.id` | `tasks.id` and `tasks.legacy_id` | Numeric task IDs preserved as primary keys. |
| `tasks.data` JSON | `tasks.*` normalized columns | Parsed into the app columns used by templates/API. |
| `tasks.data` JSON | `tasks.legacy_raw` | Raw JSON preserved to avoid data loss. |
| `subtarefas[].id` | `subtasks.legacy_id` | Preserved as text because some legacy IDs are decimal numbers. |
| `subtarefas[]` | `subtasks.*` | Imported as normalized child rows. |

## Import Rule

On a clean app database, startup imports the legacy export automatically. The manual import script can also be run with `--reset` to replace demo/scaffold data with the legacy production dataset.
