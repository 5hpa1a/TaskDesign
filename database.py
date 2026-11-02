import aiosqlite
from datetime import datetime
from config import DB_NAME


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
                completed_at TIMESTAMP
            )
        """)

        # Нормализованные таблицы
        await db.execute("""
            CREATE TABLE IF NOT EXISTS task_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL,
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


async def create_task(data: dict) -> int:
    async with aiosqlite.connect(DB_NAME) as db:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
        for pid in photos:
            await db.execute(
                "INSERT INTO task_attachments (task_id, file_id, file_type) VALUES (?, ?, 'photo')",
                (task_id, pid)
            )

        docs = data.get("reference_docs", [])
        for did in docs:
            await db.execute(
                "INSERT INTO task_attachments (task_id, file_id, file_type) VALUES (?, ?, 'doc')",
                (task_id, did)
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


async def get_task(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cur:
            task = await cur.fetchone()
            if not task:
                return None
            task_dict = dict(task)

            async with db.execute(
                "SELECT file_id, file_type FROM task_attachments WHERE task_id = ?", 
                (task_id,)
            ) as att_cur:
                attachments = await att_cur.fetchall()
                task_dict["reference_photos"] = [a["file_id"] for a in attachments if a["file_type"] == "photo"]
                task_dict["reference_docs"] = [a["file_id"] for a in attachments if a["file_type"] == "doc"]

            return task_dict


async def get_user_tasks(creator_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE creator_id = ? AND status IN ('pending', 'in_progress', 'awaiting_confirmation') ORDER BY id DESC",
            (creator_id,)
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
                    "SELECT file_id, file_type FROM task_attachments WHERE task_id = ?", (t["id"],)
                ) as att_cur:
                    atts = await att_cur.fetchall()
                    t["reference_photos"] = [a["file_id"] for a in atts if a["file_type"] == "photo"]
                    t["reference_docs"] = [a["file_id"] for a in atts if a["file_type"] == "doc"]
                result.append(t)
            return result


async def get_tasks_due_today():
    today_str = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE status = 'in_progress' AND deadline_dt LIKE ?",
            (f"{today_str}%",)
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
            query = """
                SELECT id, theme, formats, description, creator_name, creator_position, 
                       designer_name, status, created_at, deadline, deadline_dt, 
                       completed_at, reference_type, reference_data
                FROM tasks
                WHERE created_at >= datetime('now', 'start of month', '-1 month')
                ORDER BY id ASC
            """
            params = ()

        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            tasks = [dict(r) for r in rows]

        for t in tasks:
            async with db.execute(
                "SELECT file_id, file_type FROM task_attachments WHERE task_id = ?",
                (t["id"],)
            ) as att_cur:
                atts = await att_cur.fetchall()
                t["reference_photos"] = [a["file_id"] for a in atts if a["file_type"] == "photo"]
                t["reference_docs"] = [a["file_id"] for a in atts if a["file_type"] == "doc"]

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
            SET status = 'pending', designer_id = NULL, designer_name = NULL 
            WHERE id = ?
        """, (task_id,))
        await db.commit()


async def cancel_task_db(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET status = 'canceled' WHERE id = ?", (task_id,))
        await db.commit()


async def set_task_awaiting_confirmation(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET status = 'awaiting_confirmation' WHERE id = ?", (task_id,))
        await db.commit()


async def complete_task_db(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await db.execute("UPDATE tasks SET status = 'completed', completed_at = ? WHERE id = ?", (now, task_id))
        await db.commit()


async def rework_task_db(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET status = 'in_progress' WHERE id = ?", (task_id,))
        await db.commit()


async def get_monthly_designer_stats(start_date: str) -> list[dict]:
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT designer_id, designer_name, 
                   COUNT(id) as done_count,
                   AVG(strftime('%s', completed_at) - strftime('%s', created_at)) as avg_seconds
            FROM tasks
            WHERE status = 'completed' AND completed_at >= ?
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
                
                # Текст без сырого символа "<", чтобы не ломать HTML-парсер Telegram
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