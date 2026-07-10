# Legacy SQLite Schema Report

- Source DB: `C:\Users\GABRIEL.CARDOSO\Documents\ERP\Gerenciado Contabil\backups\legacy_sqlite\20260708-164559.controle.db`
- Generated at: `2026-07-08T16:45:59`
- Journal mode: `wal`

## `tasks`

- Type: `table`
- Row count: `78`
- Primary keys: `id`

### Columns

| Name | Type | Not Null | Default | PK |
| --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `0` | `None` | `1` |
| `data` | `TEXT` | `1` | `None` | `0` |

### Foreign Keys

None.

### Indexes

None.

## `users`

- Type: `table`
- Row count: `6`
- Primary keys: `id`

### Columns

| Name | Type | Not Null | Default | PK |
| --- | --- | --- | --- | --- |
| `id` | `TEXT` | `0` | `None` | `1` |
| `nome` | `TEXT` | `1` | `None` | `0` |
| `senha` | `TEXT` | `1` | `None` | `0` |
| `perfil` | `TEXT` | `1` | `None` | `0` |
| `categoria` | `TEXT` | `0` | `None` | `0` |
| `cor` | `TEXT` | `0` | `None` | `0` |

### Foreign Keys

None.

### Indexes

- `sqlite_autoindex_users_1` unique=1 origin=`pk` columns=`id`
