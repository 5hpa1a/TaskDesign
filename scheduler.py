from datetime import timedelta
import asyncio
import html
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter

import config
from config import now_msk, MSK_TZ
import database as db
from handlers import post_task_to_chat, delete_task_messages_from_group, calculate_time_left

last_morning_summary_message_id: int | None = None


async def safe_send_message(bot: Bot, chat_id: int, text: str, **kwargs):
    try:
        sent = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        await asyncio.sleep(0.08)
        return sent
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            sent = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            return sent
        except Exception:
            return None
    except Exception:
        return None


async def check_auto_approve_tasks(bot: Bot):
    """Автоматически закрывает задачи, по которым истёк срок подтверждения (18:00 след. рабочего дня UTC+3)."""
    tasks = await db.get_tasks_to_auto_approve()
    if not tasks:
        return

    for t in tasks:
        task_dict = dict(t)
        task_id = task_dict["id"]
        await db.complete_task_db(task_id)
        await delete_task_messages_from_group(bot, task_id)

        theme_escaped = html.escape(task_dict["theme"])

        # Уведомление заказчику
        await safe_send_message(
            bot,
            task_dict["creator_id"],
            f"⏱ <b>Задача #{task_id} («{theme_escaped}») автоматически закрыта и отмечена как выполненная</b>, "
            f"так как подтверждение не поступило до 18:00 следующего рабочего дня (UTC+3)."
        )

        # Уведомление дизайнеру
        if task_dict.get("designer_id"):
            await safe_send_message(
                bot,
                task_dict["designer_id"],
                f"🎉 <b>Задача #{task_id} («{theme_escaped}») автоматически закрыта как выполненная</b> "
                f"(истекло время ожидания проверки заказчиком) и засчитана в вашу статистику!"
            )


async def send_morning_tasks_summary(bot: Bot):
    global last_morning_summary_message_id

    if last_morning_summary_message_id:
        try:
            await bot.delete_message(chat_id=config.MAIN_CHAT_ID, message_id=last_morning_summary_message_id)
        except Exception:
            pass
        last_morning_summary_message_id = None

    active_tasks = await db.get_all_active_tasks()
    if not active_tasks:
        return

    status_labels = {
        "pending": "В поиске",
        "in_progress": "В работе",
        "awaiting_confirmation": "На проверке"
    }

    lines = [f"📋 <b>Утренняя сводка по активным задачам ({now_msk().strftime('%d.%m.%Y')}):</b>\n"]
    for t in active_tasks:
        t_dict = dict(t)
        theme = html.escape(t_dict["theme"])
        creator_str = f"{html.escape(t_dict['creator_name'])}"
        designer_str = f"{html.escape(t_dict['designer_name'])}" if t_dict.get("designer_name") else "Не взят"
        deadline = html.escape(t_dict.get("deadline") or "—")
        time_left = calculate_time_left(t_dict.get("deadline_dt"), t_dict.get("deadline", ""))
        status = status_labels.get(t_dict["status"], t_dict["status"])

        lines.append(
            f"• Задача #{t_dict['id']} — <b>{theme}</b> — "
            f"Заказчик: {creator_str} — "
            f"Дизайнер: {designer_str} — "
            f"Дедлайн: {deadline} (осталось: <code>{time_left}</code>) — "
            f"<i>{status}</i>"
        )

    text = "\n\n".join(lines)
    sent = await safe_send_message(bot, config.MAIN_CHAT_ID, text, disable_web_page_preview=True)
    if sent:
        last_morning_summary_message_id = sent.message_id


async def repost_pending_tasks(bot: Bot):
    tasks = await db.get_pending_tasks()
    if not tasks:
        return

    for task in tasks:
        await delete_task_messages_from_group(bot, task["id"])
        await asyncio.sleep(0.2)
        try:
            await post_task_to_chat(bot, task, task["id"])
        except Exception:
            pass


async def remind_designers_about_deadlines(bot: Bot):
    tasks = await db.get_tasks_due_today()
    if not tasks:
        return

    for task in tasks:
        if task["designer_id"]:
            text = (
                f"⏰ <b>Напоминание о дедлайне!</b>\n\n"
                f"Сегодня наступает дедлайн по задаче #{task['id']}:\n"
                f"📌 <b>Тема:</b> {html.escape(task['theme'])}\n"
                f"⏳ <b>Время сдачи:</b> {html.escape(task['deadline'])}\n"
                f"👤 <b>Заказчик:</b> {html.escape(task['creator_name'])}\n\n"
                f"Пожалуйста, не забудьте закончить макеты и нажать «Выполнено»."
            )
            await safe_send_message(bot, task["designer_id"], text)


async def send_monthly_report(bot: Bot):
    now = now_msk()
    first_day_current_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day_prev_month = first_day_current_month - timedelta(days=1)
    first_day_prev_month = last_day_prev_month.replace(day=1)

    start_date = first_day_prev_month.strftime("%Y-%m-%d %H:%M:%S")
    stats = await db.get_monthly_designer_stats(start_date)
    admins = config.load_ids_from_file(config.ADMINS_FILE)

    month_str = first_day_prev_month.strftime("%m.%Y")
    if not stats:
        report_text = f"📊 <b>Ежемесячный отчёт за {month_str}</b>\n\nВыполненных задач нет."
    else:
        report_lines = [f"📊 <b>Ежемесячный отчёт по дизайнерам за {month_str}:</b>\n"]
        for idx, row in enumerate(stats, start=1):
            d_name = html.escape(row["designer_name"] or "Аноним")
            count = row["done_count"]
            avg_time = html.escape(row["avg_time_str"])
            report_lines.append(f"{idx}. <b>{d_name}</b>: {count} задач(и) | Среднее время: <code>{avg_time}</code>")
        report_text = "\n".join(report_lines)

    for admin_id in admins:
        await safe_send_message(bot, admin_id, report_text)


async def cleanup_old_references_job():
    deleted_count = await db.cleanup_old_completed_attachments(days=30)
    if deleted_count:
        print(f"[Scheduler] Очищено старых вложений (старше 30 дней): {deleted_count}")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=MSK_TZ)
    scheduler.add_job(check_auto_approve_tasks, trigger="interval", minutes=1, args=[bot])
    scheduler.add_job(cleanup_old_references_job, trigger="cron", hour=3, minute=0)
    scheduler.add_job(send_monthly_report, trigger="cron", day=1, hour=0, minute=0, args=[bot])
    scheduler.add_job(send_morning_tasks_summary, trigger="cron", hour=9, minute=59, args=[bot])
    scheduler.add_job(repost_pending_tasks, trigger="cron", hour=10, minute=0, args=[bot])
    scheduler.add_job(remind_designers_about_deadlines, trigger="cron", hour=10, minute=0, args=[bot])
    return scheduler