import aiosqlite
from datetime import timedelta
from config import DB_NAME, now_msk


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                position TEXT NOT NULL,
                username TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                creator_name TEXT NOT NULL,
                creator_username TEXT,
                creator_position TEXT,
                theme TEXT NOT NULL,
                formats TEXT NOT NULL,
                description TEXT NOT NULL,
                deadline TEXT NOT NULL,
                deadline_dt TEXT,
                reference_type TEXT,
                reference_data TEXT,
                status TEXT NOT NULL,
                designer_id INTEGER,
                designer_name TEXT,
                created_at TIMESTAMP,
                completed_at TIMESTAMP,
                auto_approve_at TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS task_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_name TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS task_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS task_subtasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                designer_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                is_done INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
            )
        """)

        try:
            await db.execute("ALTER TABLE tasks ADD COLUMN designer_notes TEXT")
        except Exception:
            pass

        await db.execute("CREATE INDEX IF NOT EXISTS idx_subtasks_task_designer ON task_subtasks(task_id, designer_id)")

        # Безопасная миграция для существующих БД
        try:
            await db.execute("ALTER TABLE tasks ADD COLUMN auto_approve_at TEXT")
        except Exception:
            pass

        try:
            await db.execute("ALTER TABLE task_attachments ADD COLUMN file_name TEXT")
        except Exception:
            pass

        await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_attachments_task ON task_attachments(task_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_task ON task_messages(task_id)")

        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, full_name, position, username FROM users WHERE user_id = ?",
            (user_id,)
        ) as cur:
            return await cur.fetchone()


async def create_user(user_id: int, full_name: str, position: str, username: str | None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, full_name, position, username) VALUES (?, ?, ?, ?)",
            (user_id, full_name, position, username)
        )
        await db.commit()


def _normalize_attachment_item(item) -> tuple[str, str | None]:
    """Поддерживает как старый формат (str file_id), так и новый (dict {'file_id', 'file_name'})."""
    if isinstance(item, dict):
        return item["file_id"], item.get("file_name")
    return str(item), None


async def create_task(data: dict) -> int:
    async with aiosqlite.connect(DB_NAME) as db:
        now = now_msk().strftime("%Y-%m-%d %H:%M:%S")

        cursor = await db.execute("""
            INSERT INTO tasks (
                creator_id, creator_name, creator_username, creator_position,
                theme, formats, description, deadline, deadline_dt,
                reference_type, reference_data, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            data["creator_id"],
            data["creator_name"],
            data.get("creator_username"),
            data.get("creator_position"),
            data["theme"],
            data["formats"],
            data["description"],
            data["deadline"],
            data.get("deadline_dt"),
            data.get("reference_type"),
            data.get("reference_data"),
            now
        ))
        task_id = cursor.lastrowid

        photos = data.get("reference_photos", [])
        for p in photos:
            pid, fname = _normalize_attachment_item(p)
            await db.execute(
                "INSERT INTO task_attachments (task_id, file_id, file_type, file_name) VALUES (?, ?, 'photo', ?)",
                (task_id, pid, fname)
            )

        docs = data.get("reference_docs", [])
        for d in docs:
            did, fname = _normalize_attachment_item(d)
            await db.execute(
                "INSERT INTO task_attachments (task_id, file_id, file_type, file_name) VALUES (?, ?, 'doc', ?)",
                (task_id, did, fname)
            )

        await db.commit()
        return task_id


async def update_task_group_messages(task_id: int, chat_id: int, message_ids: list[int]):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM task_messages WHERE task_id = ?", (task_id,))
        for mid in message_ids:
            await db.execute(
                "INSERT INTO task_messages (task_id, chat_id, message_id) VALUES (?, ?, ?)",
                (task_id, chat_id, mid)
            )
        await db.commit()


async def get_task_messages_ids(task_id: int) -> list[int]:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT message_id FROM task_messages WHERE task_id = ?", (task_id,)) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


async def get_attachment_info(file_id: str) -> dict | None:
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT file_id, file_type, file_name FROM task_attachments WHERE file_id = ? LIMIT 1",
            (file_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_task(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cur:
            task = await cur.fetchone()
            if not task:
                return None
            task_dict = dict(task)

            async with db.execute(
                "SELECT file_id, file_type, file_name FROM task_attachments WHERE task_id = ?",
                (task_id,)
            ) as att_cur:
                attachments = await att_cur.fetchall()
                task_dict["reference_photos"] = [a["file_id"] for a in attachments if a["file_type"] == "photo"]
                task_dict["reference_docs"] = [a["file_id"] for a in attachments if a["file_type"] == "doc"]
                task_dict["attachments_full"] = [dict(a) for a in attachments]

            return task_dict


async def get_user_tasks(creator_id: int):
    """
    Возвращает активные задачи заказчика, а также выполненные (completed) задачи,
    с момента закрытия которых прошло не более 7 дней (для возможности переоткрытия).
    """
    cutoff_str = (now_msk() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM tasks 
            WHERE creator_id = ? 
              AND (
                  status IN ('pending', 'in_progress', 'awaiting_confirmation')
                  OR (status = 'completed' AND completed_at IS NOT NULL AND completed_at >= ?)
              )
            ORDER BY 
                CASE WHEN status = 'completed' THEN 1 ELSE 0 END ASC,
                id DESC
            """,
            (creator_id, cutoff_str)
        ) as cur:
            return await cur.fetchall()


async def get_designer_tasks(designer_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE designer_id = ? AND status IN ('in_progress', 'awaiting_confirmation') ORDER BY id DESC",
            (designer_id,)
        ) as cur:
            return await cur.fetchall()


async def get_all_active_tasks():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE status IN ('pending', 'in_progress', 'awaiting_confirmation') ORDER BY id ASC"
        ) as cur:
            return await cur.fetchall()


async def get_pending_tasks():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE status = 'pending'") as cur:
            rows = await cur.fetchall()
            result = []
            for r in rows:
                t = dict(r)
                async with db.execute(
                    "SELECT file_id, file_type, file_name FROM task_attachments WHERE task_id = ?", (t["id"],)
                ) as att_cur:
                    atts = await att_cur.fetchall()
                    t["reference_photos"] = [a["file_id"] for a in atts if a["file_type"] == "photo"]
                    t["reference_docs"] = [a["file_id"] for a in atts if a["file_type"] == "doc"]
                result.append(t)
            return result


async def get_tasks_due_today():
    today_str = now_msk().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE status = 'in_progress' AND deadline_dt LIKE ?",
            (f"{today_str}%",)
        ) as cur:
            return await cur.fetchall()


async def get_tasks_to_auto_approve():
    now_str = now_msk().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE status = 'awaiting_confirmation' AND auto_approve_at IS NOT NULL AND auto_approve_at <= ?",
            (now_str,)
        ) as cur:
            return await cur.fetchall()


async def get_available_task_months() -> list[str]:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT DISTINCT substr(created_at, 1, 7) as ym 
            FROM tasks 
            WHERE created_at IS NOT NULL 
            ORDER BY ym DESC
        """) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows if r[0]]


async def get_tasks_for_webapp(month_filter: str | None = None):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        if month_filter:
            query = """
                SELECT id, theme, formats, description, creator_name, creator_position, 
                       designer_name, status, created_at, deadline, deadline_dt, 
                       completed_at, reference_type, reference_data
                FROM tasks
                WHERE created_at LIKE ?
                ORDER BY id ASC
            """
            params = (f"{month_filter}%",)
        else:
            now_str = now_msk().strftime("%Y-%m-%d %H:%M:%S")
            query = """
                SELECT id, theme, formats, description, creator_name, creator_position, 
                       designer_name, status, created_at, deadline, deadline_dt, 
                       completed_at, reference_type, reference_data
                FROM tasks
                WHERE created_at >= datetime(?, 'start of month', '-1 month')
                ORDER BY id ASC
            """
            params = (now_str,)

        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            tasks = [dict(r) for r in rows]

        for t in tasks:
            async with db.execute(
                "SELECT file_id, file_type, file_name FROM task_attachments WHERE task_id = ?",
                (t["id"],)
            ) as att_cur:
                atts = await att_cur.fetchall()
                t["reference_photos"] = [a["file_id"] for a in atts if a["file_type"] == "photo"]
                t["reference_docs"] = [a["file_id"] for a in atts if a["file_type"] == "doc"]
                t["attachments"] = [dict(a) for a in atts]

        return tasks


async def assign_task_to_designer(task_id: int, designer_id: int, designer_name: str) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            UPDATE tasks 
            SET status = 'in_progress', designer_id = ?, designer_name = ?
            WHERE id = ? AND status = 'pending'
        """, (designer_id, designer_name, task_id))
        await db.commit()
        return cursor.rowcount == 1


async def free_task_from_designer(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE tasks 
            SET status = 'pending', designer_id = NULL, designer_name = NULL, auto_approve_at = NULL
            WHERE id = ?
        """, (task_id,))
        await db.commit()


async def cancel_task_db(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET status = 'canceled', auto_approve_at = NULL WHERE id = ?", (task_id,))
        await db.commit()


async def set_task_awaiting_confirmation(task_id: int, auto_approve_at: str) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            UPDATE tasks 
            SET status = 'awaiting_confirmation', auto_approve_at = ? 
            WHERE id = ? AND status = 'in_progress'
            """,
            (auto_approve_at, task_id)
        )
        await db.commit()
        return cursor.rowcount == 1


async def complete_task_db(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        now = now_msk().strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            "UPDATE tasks SET status = 'completed', completed_at = ?, auto_approve_at = NULL WHERE id = ?",
            (now, task_id)
        )
        await db.commit()


async def rework_task_db(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE tasks SET status = 'in_progress', auto_approve_at = NULL WHERE id = ?",
            (task_id,)
        )
        await db.commit()


async def get_monthly_designer_stats(start_date: str) -> list[dict]:
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT designer_id, designer_name, 
                   COUNT(id) as done_count,
                   AVG(strftime('%s', completed_at) - strftime('%s', created_at)) as avg_seconds
            FROM tasks
            WHERE status = 'completed' AND completed_at >= ? AND designer_id IS NOT NULL
            GROUP BY designer_id
            ORDER BY done_count DESC
        """
        async with db.execute(query, (start_date,)) as cur:
            rows = await cur.fetchall()
            results = []
            for r in rows:
                avg_sec = r["avg_seconds"] or 0
                days = int(avg_sec // 86400)
                hours = int((avg_sec % 86400) // 3600)

                if days > 0 or hours > 0:
                    time_str = f"{days} д. {hours} ч."
                else:
                    time_str = "менее 1 ч."

                results.append({
                    "designer_id": r["designer_id"],
                    "designer_name": r["designer_name"],
                    "done_count": r["done_count"],
                    "avg_time_str": time_str
                })
            return results


async def update_task_deadline(task_id: int, deadline: str, deadline_dt: str | None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE tasks
            SET deadline = ?, deadline_dt = ?
            WHERE id = ?
        """, (deadline, deadline_dt, task_id))
        await db.commit()


async def update_task_description(task_id: int, description: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE tasks
            SET description = ?
            WHERE id = ?
        """, (description, task_id))
        await db.commit()

async def reopen_task_db(task_id: int, has_designer: bool):
    """Переоткрывает завершённую задачу на доработку."""
    new_status = "in_progress" if has_designer else "pending"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            UPDATE tasks 
            SET status = ?, completed_at = NULL, auto_approve_at = NULL 
            WHERE id = ?
            """,
            (new_status, task_id)
        )
        await db.commit()

async def cleanup_old_completed_attachments(days: int = 30) -> int:
    """
    Удаляет референсы (вложения из task_attachments и текстовые референсы)
    у задач, которые были выполнены более `days` дней назад.
    """
    cutoff_str = (now_msk() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            DELETE FROM task_attachments
            WHERE task_id IN (
                SELECT id FROM tasks
                WHERE status = 'completed'
                  AND completed_at IS NOT NULL
                  AND completed_at <= ?
            )
            """,
            (cutoff_str,)
        )
        deleted_attachments = cursor.rowcount

        await db.execute(
            """
            UPDATE tasks
            SET reference_data = NULL, reference_type = 'cleaned'
            WHERE status = 'completed'
              AND completed_at IS NOT NULL
              AND completed_at <= ?
              AND (reference_data IS NOT NULL OR reference_type != 'cleaned')
            """,
            (cutoff_str,)
        )
        await db.commit()
        return deleted_attachments

async def get_designer_cabinet_data(designer_id: int) -> dict:
    """Возвращает активные задачи дизайнера (с подзадачами, вложениями и заметками) и свободные задачи."""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        # 1. Задачи текущего дизайнера
        async with db.execute(
            """
            SELECT * FROM tasks 
            WHERE designer_id = ? AND status IN ('in_progress', 'awaiting_confirmation') 
            ORDER BY id DESC
            """,
            (designer_id,)
        ) as cur:
            my_rows = await cur.fetchall()
            my_tasks = [dict(r) for r in my_rows]

        for t in my_tasks:
            async with db.execute(
                "SELECT file_id, file_type, file_name FROM task_attachments WHERE task_id = ?",
                (t["id"],)
            ) as att_cur:
                atts = await att_cur.fetchall()
                t["attachments"] = [dict(a) for a in atts]

            async with db.execute(
                "SELECT id, title, is_done FROM task_subtasks WHERE task_id = ? AND designer_id = ? ORDER BY id ASC",
                (t["id"], designer_id)
            ) as sub_cur:
                subs = await sub_cur.fetchall()
                t["subtasks"] = [
                    {"id": s["id"], "title": s["title"], "is_done": bool(s["is_done"])}
                    for s in subs
                ]

        # 2. Свободные задачи (в поиске)
        async with db.execute(
            "SELECT * FROM tasks WHERE status = 'pending' ORDER BY id DESC"
        ) as cur:
            avail_rows = await cur.fetchall()
            available_tasks = [dict(r) for r in avail_rows]

        for t in available_tasks:
            async with db.execute(
                "SELECT file_id, file_type, file_name FROM task_attachments WHERE task_id = ?",
                (t["id"],)
            ) as att_cur:
                atts = await att_cur.fetchall()
                t["attachments"] = [dict(a) for a in atts]

        return {
            "my_tasks": my_tasks,
            "available_tasks": available_tasks
        }


async def add_task_subtask(task_id: int, designer_id: int, title: str) -> dict:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "INSERT INTO task_subtasks (task_id, designer_id, title, is_done) VALUES (?, ?, ?, 0)",
            (task_id, designer_id, title)
        )
        await db.commit()
        return {"id": cursor.lastrowid, "title": title, "is_done": False}


async def toggle_task_subtask(subtask_id: int, designer_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            UPDATE task_subtasks 
            SET is_done = CASE WHEN is_done = 1 THEN 0 ELSE 1 END
            WHERE id = ? AND designer_id = ?
            """,
            (subtask_id, designer_id)
        )
        await db.commit()
        return cursor.rowcount == 1


async def update_task_subtask_title(subtask_id: int, designer_id: int, title: str) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "UPDATE task_subtasks SET title = ? WHERE id = ? AND designer_id = ?",
            (title, subtask_id, designer_id)
        )
        await db.commit()
        return cursor.rowcount == 1


async def delete_task_subtask(subtask_id: int, designer_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "DELETE FROM task_subtasks WHERE id = ? AND designer_id = ?",
            (subtask_id, designer_id)
        )
        await db.commit()
        return cursor.rowcount == 1


async def update_designer_task_notes(task_id: int, designer_id: int, notes: str) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "UPDATE tasks SET designer_notes = ? WHERE id = ? AND designer_id = ?",
            (notes, task_id, designer_id)
        )
        await db.commit()
        return cursor.rowcount == 1

async def get_tasks_awaiting_confirmation_for_creator(creator_id: int | None = None) -> list[dict]:
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        if creator_id is not None:
            query = "SELECT * FROM tasks WHERE status = 'awaiting_confirmation' AND creator_id = ? ORDER BY id ASC"
            params = (creator_id,)
        else:
            query = "SELECT * FROM tasks WHERE status = 'awaiting_confirmation' ORDER BY id ASC"
            params = ()
        async with db.execute(query, params) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_in_progress_tasks_for_designer(designer_id: int | None = None) -> list[dict]:
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        if designer_id is not None:
            query = "SELECT * FROM tasks WHERE status = 'in_progress' AND designer_id = ? ORDER BY id ASC"
            params = (designer_id,)
        else:
            query = "SELECT * FROM tasks WHERE status = 'in_progress' AND designer_id IS NOT NULL ORDER BY id ASC"
            params = ()
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            result = []
            for r in rows:
                t = dict(r)
                async with db.execute(
                    "SELECT file_id, file_type, file_name FROM task_attachments WHERE task_id = ?",
                    (t["id"],)
                ) as att_cur:
                    atts = await att_cur.fetchall()
                    t["reference_photos"] = [a["file_id"] for a in atts if a["file_type"] == "photo"]
                    t["reference_docs"] = [a["file_id"] for a in atts if a["file_type"] == "doc"]
                result.append(t)
            return result


async def get_unposted_pending_tasks() -> list[dict]:
    """Находит задачи в статусе pending, которые не были опубликованы в общий чат из-за сбоя."""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT t.* FROM tasks t
            LEFT JOIN task_messages tm ON t.id = tm.task_id
            WHERE t.status = 'pending' AND tm.id IS NULL
            ORDER BY t.id ASC
        """) as cur:
            rows = await cur.fetchall()
            result = []
            for r in rows:
                t = dict(r)
                async with db.execute(
                    "SELECT file_id, file_type, file_name FROM task_attachments WHERE task_id = ?",
                    (t["id"],)
                ) as att_cur:
                    atts = await att_cur.fetchall()
                    t["reference_photos"] = [a["file_id"] for a in atts if a["file_type"] == "photo"]
                    t["reference_docs"] = [a["file_id"] for a in atts if a["file_type"] == "doc"]
                result.append(t)
            return result