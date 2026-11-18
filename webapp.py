import io
import os
import json
import hmac
import hashlib
import mimetypes
import logging
from urllib.parse import quote, parse_qsl
from aiohttp import web
from aiogram import Bot

import config
import database as db
from handlers import (
    is_designer_position,
    execute_designer_take_task,
    execute_designer_done_task,
    execute_designer_reject_task,
)

logger = logging.getLogger(__name__)


def verify_telegram_webapp_user(init_data: str) -> dict | None:
    """Проверяет подпись Telegram WebApp initData и возвращает словарь user."""
    if not init_data:
        return None
    try:
        parsed_data = dict(parse_qsl(init_data, strict_parsing=True))
        received_hash = parsed_data.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        secret_key = hmac.new(b"WebAppData", config.BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        user_raw = parsed_data.get("user")
        return json.loads(user_raw) if user_raw else None
    except Exception as e:
        logger.warning(f"Ошибка проверки initData: {e}")
        return None


async def resolve_webapp_user_id(request: web.Request) -> int | None:
    """
    Определяет user_id открывшего Mini App:
    1. Сначала проверяет криптографически подписанный X-Telegram-Init-Data.
    2. Если initData пуст (например, открытие из старой кнопки меню), использует X-Telegram-User-Id.
    """
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if init_data:
        tg_user = verify_telegram_webapp_user(init_data)
        if tg_user and "id" in tg_user:
            return int(tg_user["id"])

    fallback_id = request.headers.get("X-Telegram-User-Id", "").strip()
    if fallback_id.isdigit():
        return int(fallback_id)

    return None

async def get_authenticated_designer(request: web.Request) -> tuple[dict | None, web.Response | None]:
    """Проверяет, что запрос пришёл от зарегистрированного дизайнера."""
    user_id = await resolve_webapp_user_id(request)
    if not user_id:
        return None, web.json_response(
            {"error": "Не удалось определить пользователя Telegram. Откройте Mini App через кнопку в боте (/start)."},
            status=401
        )

    db_user = await db.get_user(user_id)
    if not db_user:
        return None, web.json_response(
            {"error": "Вы не зарегистрированы в боте. Нажмите /start в личных сообщениях с ботом."},
            status=403
        )

    if not is_designer_position(db_user[2]):
        return None, web.json_response(
            {"error": f"Ваша должность ({db_user[2]}) не относится к дизайнерам. Эта вкладка только для дизайнеров."},
            status=403
        )

    return {
        "user_id": user_id,
        "full_name": db_user[1],
        "position": db_user[2],
        "username": db_user[3],
    }, None

async def handle_index(request: web.Request) -> web.Response:
    return web.Response(
        text=HTML_CONTENT,
        content_type='text/html',
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


async def handle_me(request: web.Request) -> web.Response:
    user_id = await resolve_webapp_user_id(request)
    if not user_id:
        return web.json_response({"is_designer": False, "is_admin": False, "reason": "no_user_id"})

    db_user = await db.get_user(user_id)
    if not db_user:
        return web.json_response({"is_designer": False, "is_admin": False, "reason": "not_registered"})

    is_des = is_designer_position(db_user[2])
    is_adm = config.is_admin(user_id)
    return web.json_response({
        "user_id": user_id,
        "full_name": db_user[1],
        "position": db_user[2],
        "is_designer": is_des,
        "is_admin": is_adm,
    })

HTML_CONTENT = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>TaskManager — Дизайн</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        :root {
            --bg-color: var(--tg-theme-bg-color, #f4f6f9);
            --text-color: var(--tg-theme-text-color, #222);
            --card-bg: var(--tg-theme-secondary-bg-color, #ffffff);
            --hint-color: var(--tg-theme-hint-color, #8e8e93);
            --link-color: var(--tg-theme-link-color, #007aff);
            --border-color: rgba(0, 0, 0, 0.08);
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 12px;
            background-color: var(--bg-color);
            color: var(--text-color);
            box-sizing: border-box;
        }

        .top-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 10px;
            gap: 8px;
        }

        h2 {
            margin: 0;
            font-size: 19px;
        }

        .refresh-btn {
            background-color: var(--card-bg);
            color: var(--link-color);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 7px 12px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 5px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.04);
        }
        .refresh-btn:disabled { opacity: 0.6; }

        /* Навигация по вкладкам */
        .nav-tabs {
            display: flex;
            gap: 8px;
            background-color: var(--card-bg);
            padding: 6px;
            border-radius: 12px;
            margin-bottom: 14px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        }
        .nav-tab-btn {
            flex: 1;
            padding: 9px 10px;
            border: none;
            border-radius: 8px;
            background: transparent;
            color: var(--text-color);
            font-size: 13px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.15s ease;
        }
        .nav-tab-btn.active {
            background-color: var(--link-color);
            color: #fff;
        }

        .filters-card {
            background-color: var(--card-bg);
            border-radius: 12px;
            padding: 12px;
            margin-bottom: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .filter-row { display: flex; gap: 8px; }
        .filter-group { flex: 1; display: flex; flex-direction: column; gap: 4px; }
        .filter-group label {
            font-size: 11px;
            font-weight: 600;
            color: var(--hint-color);
            text-transform: uppercase;
        }

        select, input, textarea {
            width: 100%;
            padding: 8px 10px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            background-color: var(--bg-color);
            color: var(--text-color);
            font-size: 13px;
            outline: none;
            box-sizing: border-box;
            font-family: inherit;
        }

        .status-buttons-container { display: flex; flex-direction: column; gap: 6px; }
        .chips-scroll {
            display: flex;
            gap: 6px;
            overflow-x: auto;
            padding-bottom: 4px;
            scrollbar-width: none;
        }
        .chips-scroll::-webkit-scrollbar { display: none; }

        .chip-btn {
            background-color: var(--bg-color);
            color: var(--text-color);
            border: 1px solid var(--border-color);
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            white-space: nowrap;
        }
        .chip-btn.active {
            background-color: var(--link-color);
            color: #fff;
            border-color: var(--link-color);
        }
        .chip-active-group {
            background-color: rgba(0, 122, 255, 0.12);
            color: var(--link-color);
            border-color: rgba(0, 122, 255, 0.3);
        }
        .chip-active-group.active { background-color: var(--link-color); color: #fff; }

        .month-section { margin-bottom: 20px; }
        .month-header {
            font-size: 15px;
            font-weight: 700;
            color: var(--link-color);
            padding: 6px 4px;
            margin-bottom: 6px;
            border-bottom: 2px solid var(--link-color);
            display: flex;
            justify-content: space-between;
        }
        .month-count { font-size: 12px; color: var(--hint-color); font-weight: normal; }

        .task-table-container {
            width: 100%;
            overflow-x: auto;
            background-color: var(--card-bg);
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        }

        table.main-table { width: 100%; border-collapse: collapse; text-align: left; font-size: 12px; white-space: nowrap; }
        table.main-table th {
            background-color: rgba(0, 0, 0, 0.03);
            color: var(--hint-color);
            padding: 10px 12px;
            font-size: 11px;
            text-transform: uppercase;
            font-weight: 600;
            border-bottom: 1px solid var(--border-color);
        }
        table.main-table td { padding: 10px 12px; border-bottom: 1px solid var(--border-color); }
        tbody tr { cursor: pointer; }
        tbody tr:hover { background-color: rgba(0, 122, 255, 0.06); }
        tr:last-child td { border-bottom: none; }

        .task-id { font-weight: 700; color: var(--hint-color); }
        .task-theme { font-weight: 600; max-width: 160px; overflow: hidden; text-overflow: ellipsis; }
        .task-date { color: var(--hint-color); font-size: 11px; }

        .status-badge { display: inline-block; padding: 2px 6px; border-radius: 5px; font-size: 11px; font-weight: 600; }
        .status-pending { background-color: #fff3cd; color: #856404; }
        .status-in_progress { background-color: #cce5ff; color: #004085; }
        .status-awaiting_confirmation { background-color: #e2e3e5; color: #383d41; }
        .status-completed { background-color: #d4edda; color: #155724; }
        .status-canceled { background-color: #f8d7da; color: #721c24; }

        .sla-ontime { color: #28a745; font-weight: 600; }
        .sla-overdue { color: #dc3545; font-weight: 600; }
        .sla-pending { color: #ffc107; font-weight: 600; }
        .empty-placeholder { text-align: center; padding: 26px; color: var(--hint-color); font-size: 14px; }

        /* Карточки в ЛК Дизайнера */
        .cab-section-title {
            font-size: 15px;
            font-weight: 700;
            margin: 14px 0 8px 2px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .cab-cards-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .cab-card {
            background-color: var(--card-bg);
            border-radius: 12px;
            padding: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
            border: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .cab-card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 8px;
        }
        .cab-card-title {
            font-size: 14px;
            font-weight: 700;
            margin: 0;
        }
        .cab-meta {
            font-size: 12px;
            color: var(--hint-color);
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }

        /* Прогресс-бар подзадач */
        .progress-wrapper {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .progress-label-row {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            font-weight: 600;
            color: var(--hint-color);
        }
        .progress-track {
            width: 100%;
            height: 7px;
            background-color: var(--bg-color);
            border-radius: 6px;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }
        .progress-fill {
            height: 100%;
            background-color: #28a745;
            transition: width 0.25s ease;
        }

        /* Кнопки действий */
        .action-row {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 2px;
        }
        .btn {
            padding: 8px 12px;
            border-radius: 8px;
            border: none;
            font-size: 12px;
            font-weight: 700;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
            flex: 1;
        }
        .btn:disabled { opacity: 0.55; cursor: default; }
        .btn-primary { background-color: var(--link-color); color: #fff; }
        .btn-success { background-color: #28a745; color: #fff; }
        .btn-danger { background-color: #dc3545; color: #fff; }
        .btn-secondary {
            background-color: var(--bg-color);
            color: var(--text-color);
            border: 1px solid var(--border-color);
        }

        /* Блок чек-листа и заметок в модалке */
        .workspace-box {
            background-color: var(--bg-color);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 10px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .subtask-add-row {
            display: flex;
            gap: 6px;
        }
        .subtask-add-row input {
            background-color: var(--card-bg);
        }
        .subtask-add-row button {
            flex: 0 0 auto;
            padding: 8px 12px;
        }
        .subtask-list {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .subtask-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            background-color: var(--card-bg);
            padding: 6px 8px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }
        .subtask-left {
            display: flex;
            align-items: center;
            gap: 8px;
            flex: 1;
            min-width: 0;
        }
        .subtask-left input[type="checkbox"] {
            width: 16px;
            height: 16px;
            margin: 0;
            cursor: pointer;
            flex-shrink: 0;
        }
        .subtask-text {
            font-size: 12px;
            word-break: break-word;
        }
        .subtask-text.done {
            text-decoration: line-through;
            color: var(--hint-color);
        }
        .subtask-actions {
            display: flex;
            gap: 4px;
            flex-shrink: 0;
        }
        .icon-mini-btn {
            background: transparent;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 3px 6px;
            font-size: 11px;
            cursor: pointer;
            color: var(--text-color);
        }

        /* Модальное окно */
        .modal-overlay {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background-color: rgba(0, 0, 0, 0.45);
            display: none; justify-content: center; align-items: center;
            z-index: 1000; padding: 12px; box-sizing: border-box; backdrop-filter: blur(2px);
        }
        .modal-card {
            background-color: var(--card-bg); color: var(--text-color);
            width: 100%; max-width: 520px; max-height: 92vh;
            border-radius: 14px; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
            display: flex; flex-direction: column; overflow: hidden;
        }
        .modal-header { padding: 12px 14px; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center; }
        .modal-title { font-size: 15px; font-weight: 700; margin: 0; }
        .modal-close { background: none; border: none; font-size: 22px; cursor: pointer; color: var(--hint-color); line-height: 1; padding: 0 4px; }
        .modal-body {
            padding: 12px 14px;
            overflow-y: auto;
            font-size: 12px;
            line-height: 1.4;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .modal-info-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            background-color: var(--bg-color);
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }
        .modal-info-table td { padding: 5px 8px; border-bottom: 1px solid var(--border-color); vertical-align: middle; }
        .modal-info-table tr:last-child td { border-bottom: none; }
        .modal-info-table .info-label {
            width: 110px;
            font-size: 11px;
            font-weight: 700;
            color: var(--hint-color);
            text-transform: uppercase;
            white-space: nowrap;
        }
        .modal-info-table .info-val { font-weight: 500; word-break: break-word; }

        .modal-field { display: flex; flex-direction: column; gap: 4px; }
        .modal-label { font-size: 11px; text-transform: uppercase; font-weight: 700; color: var(--hint-color); }
        .modal-value { font-weight: 500; word-break: break-word; }
        .modal-desc-box {
            background-color: var(--bg-color); border: 1px solid var(--border-color);
            border-radius: 8px; padding: 8px 10px; max-height: 140px; overflow-y: auto;
            white-space: pre-wrap; font-family: inherit; font-size: 12px;
        }

        .photo-gallery { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
        .gallery-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
            width: 76px;
        }
        .gallery-item.expanded { width: 100% !important; }
        .gallery-thumb {
            width: 100%; height: 72px; object-fit: cover; border-radius: 6px;
            cursor: pointer; border: 1px solid var(--border-color);
            background-color: var(--bg-color);
        }
        .gallery-item.expanded .gallery-thumb {
            height: auto !important; max-height: 440px;
            object-fit: contain; border: 1px solid var(--link-color);
        }
        .img-download-link {
            display: inline-block;
            width: 100%;
            text-align: center;
            padding: 3px 4px;
            font-size: 10px;
            font-weight: 600;
            color: var(--link-color);
            background-color: var(--bg-color);
            border: 1px solid var(--border-color);
            border-radius: 5px;
            text-decoration: none;
            box-sizing: border-box;
        }
        .files-list { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
        .file-download-btn {
            display: inline-flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            padding: 8px 10px;
            background-color: var(--bg-color);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--link-color);
            text-decoration: none;
            font-size: 12px;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div id="mainAppContent">
        <div class="top-bar">
            <h2>📋 TaskManager</h2>
            <button id="refreshBtn" class="refresh-btn" onclick="refreshAll()">🔄 Обновить</button>
        </div>

        <!-- Вкладки навигации (вкладка ЛК показывается только дизайнерам) -->
        <div class="nav-tabs" id="navTabs">
            <button class="nav-tab-btn active" id="tabBtnAll" onclick="switchTab('all')">📊 Все задачи</button>
            <button class="nav-tab-btn" id="tabBtnCabinet" onclick="switchTab('cabinet')">🎨 Мой кабинет</button>
        </div>

        <!-- ВКЛАДКА 1: ОБЩАЯ ТАБЛИЦА ЗАДАЧ -->
        <div id="tabAllContent">
            <div class="filters-card">
                <div class="filter-row">
                    <div class="filter-group">
                        <label>Период</label>
                        <select id="filter-month">
                            <option value="">Последние 2 месяца</option>
                        </select>
                    </div>
                    <div class="filter-group">
                        <label>Поиск по теме</label>
                        <input type="text" id="filter-search" placeholder="Поиск темы...">
                    </div>
                </div>

                <div class="filter-row">
                    <div class="filter-group">
                        <label>Заказчик</label>
                        <select id="filter-creator">
                            <option value="">Все заказчики</option>
                        </select>
                    </div>
                    <div class="filter-group">
                        <label>Дизайнер</label>
                        <select id="filter-designer">
                            <option value="">Все дизайнеры</option>
                        </select>
                    </div>
                </div>

                <div class="status-buttons-container">
                    <label style="font-size: 11px; font-weight: 600; color: var(--hint-color); text-transform: uppercase;">Статус задачи</label>
                    <div class="chips-scroll">
                        <button class="chip-btn active" data-status="">Все</button>
                        <button class="chip-btn chip-active-group" data-status="ACTIVE_ONLY">⚡ Только активные</button>
                        <button class="chip-btn" data-status="pending">В поиске</button>
                        <button class="chip-btn" data-status="in_progress">В работе</button>
                        <button class="chip-btn" data-status="awaiting_confirmation">На проверке</button>
                        <button class="chip-btn" data-status="completed">Завершены</button>
                        <button class="chip-btn" data-status="canceled">Отменены</button>
                    </div>
                </div>
            </div>

            <div id="tasks-container">
                <div class="empty-placeholder">Загрузка задач...</div>
            </div>
        </div>

        <!-- ВКЛАДКА 2: ЛИЧНЫЙ КАБИНЕТ ДИЗАЙНЕРА -->
        <div id="tabCabinetContent" style="display: none;">
            <div id="cabinetBody">
                <div class="empty-placeholder">Загрузка личного кабинета...</div>
            </div>
        </div>
    </div>

    <!-- Модальное окно задачи -->
    <div class="modal-overlay" id="taskModal" onclick="closeModalOnOverlay(event)">
        <div class="modal-card">
            <div class="modal-header">
                <h3 class="modal-title" id="mTaskTitle">Задача #0</h3>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body">
                <table class="modal-info-table">
                    <tr>
                        <td class="info-label">Тема</td>
                        <td class="info-val" id="mTheme"></td>
                    </tr>
                    <tr>
                        <td class="info-label">Форматы</td>
                        <td class="info-val" id="mFormats"></td>
                    </tr>
                    <tr>
                        <td class="info-label">Дата создания</td>
                        <td class="info-val" id="mCreatedAt"></td>
                    </tr>
                    <tr>
                        <td class="info-label">Заказчик</td>
                        <td class="info-val" id="mCreator"></td>
                    </tr>
                    <tr>
                        <td class="info-label">Дизайнер</td>
                        <td class="info-val" id="mDesigner"></td>
                    </tr>
                    <tr>
                        <td class="info-label">Статус и сроки</td>
                        <td class="info-val" id="mStatusSla"></td>
                    </tr>
                </table>

                <!-- 1. Сначала ТЗ и Референсы / Вложения -->
                <div class="modal-field">
                    <span class="modal-label">Техническое задание (ТЗ)</span>
                    <div class="modal-desc-box" id="mDescription"></div>
                </div>

                <div class="modal-field">
                    <span class="modal-label">Референсы / Вложения</span>
                    <span class="modal-value" id="mReferencesText"></span>
                    <div class="photo-gallery" id="mPhotoGallery"></div>
                    <div class="files-list" id="mFilesList"></div>
                </div>

                <!-- 2. Ниже — Подзадачи, Личные заметки и Кнопки управления -->
                <div id="designerWorkspaceSection" style="display: none; flex-direction: column; gap: 10px;">
                    <div class="workspace-box">
                        <div class="progress-wrapper">
                            <div class="progress-label-row">
                                <span>📌 Подзадачи (чек-лист)</span>
                                <span id="mSubtaskProgressText">0/0 (0%)</span>
                            </div>
                            <div class="progress-track">
                                <div class="progress-fill" id="mSubtaskProgressBar" style="width: 0%;"></div>
                            </div>
                        </div>

                        <div class="subtask-add-row">
                            <input type="text" id="newSubtaskInput" placeholder="Новая подзадача (напр. Адаптив 1080x1920)..." onkeydown="if(event.key==='Enter') handleAddSubtask()">
                            <button class="btn btn-primary" onclick="handleAddSubtask()">+ Добавить</button>
                        </div>

                        <div class="subtask-list" id="mSubtaskList"></div>
                    </div>

                    <div class="workspace-box">
                        <span class="modal-label">📝 Личные заметки (видны только вам)</span>
                        <textarea id="mDesignerNotes" rows="3" placeholder="Ваши личные пометки, ссылки, размеры, цвета..."></textarea>
                        <div style="display: flex; justify-content: flex-end;">
                            <button class="btn btn-secondary" style="flex: 0 0 auto;" id="saveNotesBtn" onclick="handleSaveNotes()">💾 Сохранить заметку</button>
                        </div>
                    </div>

                    <div class="action-row" id="mDesignerControlButtons"></div>
                </div>

                <!-- Кнопка «Взять в работу» для свободной задачи в ЛК -->
                <div id="designerTakeSection" style="display: none;">
                    <button class="btn btn-primary" style="width: 100%;" id="mTakeTaskBtn">💼 Взять задачу в работу</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        const tg = window.Telegram?.WebApp;
        if (tg) { tg.expand(); tg.ready(); }

        const initData = tg?.initData || "";
        const unsafeUserId = tg?.initDataUnsafe?.user?.id ? String(tg.initDataUnsafe.user.id) : "";
        const urlUid = new URLSearchParams(window.location.search).get("uid") || "";
        const resolvedUid = unsafeUserId || urlUid;
        let userRole = { is_designer: false, is_admin: false, full_name: "", position: "" };
        let activeTab = "all";

        let allTasks = [];
        let cabinetData = { my_tasks: [], available_tasks: [] };
        let currentModalTask = null;
        let currentModalMode = "readonly"; // 'readonly' | 'cabinet_my' | 'cabinet_available'
        let currentStatusFilter = "";

        const IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'];

        const statusMap = {
            "pending": { text: "В поиске", class: "status-pending" },
            "in_progress": { text: "В работе", class: "status-in_progress" },
            "awaiting_confirmation": { text: "На проверке", class: "status-awaiting_confirmation" },
            "completed": { text: "Завершена", class: "status-completed" },
            "canceled": { text: "Отменена", class: "status-canceled" }
        };

        const monthNames = [
            "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
            "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
        ];

        function apiHeaders() {
            return {
                "Content-Type": "application/json",
                "X-Telegram-Init-Data": initData,
                "X-Telegram-User-Id": resolvedUid
            };
        }

        function escapeHtml(str) {
            if (!str) return "";
            return String(str)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;");
        }

        function isImageAttachment(att) {
            if (att.file_type === 'photo') return true;
            if (!att.file_name) return false;
            const lower = att.file_name.toLowerCase();
            return IMAGE_EXTS.some(ext => lower.endsWith(ext));
        }

        async function initUserProfile() {
            try {
                const res = await fetch('/api/me', { headers: apiHeaders() });
                if (res.ok) {
                    userRole = await res.json();
                }
            } catch (e) {}

            // Если пользователь точно не дизайнер (например, только админ), скрываем кнопку вкладки,
            // а при принудительном переключении сработает заглушка в loadCabinet()
            if (userRole.user_id && !userRole.is_designer) {
                document.getElementById('navTabs').style.display = 'none';
            }
        }

        function switchTab(tab) {
            activeTab = tab;
            document.getElementById('tabBtnAll').classList.toggle('active', tab === 'all');
            document.getElementById('tabBtnCabinet').classList.toggle('active', tab === 'cabinet');
            document.getElementById('tabAllContent').style.display = tab === 'all' ? 'block' : 'none';
            document.getElementById('tabCabinetContent').style.display = tab === 'cabinet' ? 'block' : 'none';

            if (tab === 'cabinet') {
                loadCabinet();
            } else {
                const selectedMonth = document.getElementById('filter-month').value;
                loadTasks(selectedMonth);
            }
        }

        async function loadCabinet() {
            const container = document.getElementById('cabinetBody');
            if (userRole.user_id && !userRole.is_designer) {
                container.innerHTML = `<div class="empty-placeholder">⛔ Вы не являетесь дизайнером (${escapeHtml(userRole.position || 'сотрудник')}), здесь для вас ничего нет.</div>`;
                return;
            }
            container.innerHTML = '<div class="empty-placeholder">Загрузка задач кабинета...</div>';
            try {
                const res = await fetch('/api/designer/cabinet', { headers: apiHeaders() });
                const data = await res.json();
                if (!res.ok) {
                    container.innerHTML = `<div class="empty-placeholder">⛔ ${escapeHtml(data.error || 'Доступ запрещён')}</div>`;
                    return;
                }
                cabinetData = data;
                renderCabinet();
            } catch (err) {
                container.innerHTML = `<div class="empty-placeholder" style="color:#d9534f;">⚠️ Ошибка загрузки: ${escapeHtml(err.message)}</div>`;
            }
        }

        function calcSubtaskStats(subtasks) {
            const total = (subtasks || []).length;
            const done = (subtasks || []).filter(s => s.is_done).length;
            const pct = total > 0 ? Math.round((done / total) * 100) : 0;
            return { total, done, pct };
        }

        function renderCabinet() {
            const container = document.getElementById('cabinetBody');
            const myTasks = cabinetData.my_tasks || [];
            const availTasks = cabinetData.available_tasks || [];

            let html = `
                <div class="cab-section-title">
                    <span>🛠 Мои задачи в работе (${myTasks.length})</span>
                </div>
            `;

            if (myTasks.length === 0) {
                html += `<div class="cab-card"><div class="empty-placeholder" style="padding:14px;">У вас пока нет активных задач. Выберите свободную задачу ниже 👇</div></div>`;
            } else {
                html += `<div class="cab-cards-list">`;
                myTasks.forEach(t => {
                    const st = statusMap[t.status] || { text: t.status, class: "status-in_progress" };
                    const stats = calcSubtaskStats(t.subtasks);
                    const hasNotes = t.designer_notes && t.designer_notes.trim().length > 0;

                    html += `
                        <div class="cab-card">
                            <div class="cab-card-header" onclick="openCabinetTaskModal(${t.id}, 'cabinet_my')" style="cursor:pointer;">
                                <h4 class="cab-card-title">#${t.id} — ${escapeHtml(t.theme)}</h4>
                                <span class="status-badge ${st.class}">${st.text}</span>
                            </div>
                            <div class="cab-meta" onclick="openCabinetTaskModal(${t.id}, 'cabinet_my')" style="cursor:pointer;">
                                <span>👤 ${escapeHtml(t.creator_name)}</span>
                                <span>⏰ Дедлайн: <b>${escapeHtml(t.deadline || '—')}</b></span>
                                <span>📐 ${escapeHtml(t.formats)}</span>
                                ${hasNotes ? '<span>📝 Есть заметка</span>' : ''}
                            </div>
                            <div class="progress-wrapper" onclick="openCabinetTaskModal(${t.id}, 'cabinet_my')" style="cursor:pointer;">
                                <div class="progress-label-row">
                                    <span>Прогресс по подзадачам</span>
                                    <span>${stats.done}/${stats.total} (${stats.pct}%)</span>
                                </div>
                                <div class="progress-track">
                                    <div class="progress-fill" style="width: ${stats.pct}%;"></div>
                                </div>
                            </div>
                            <div class="action-row">
                                <button class="btn btn-secondary" onclick="openCabinetTaskModal(${t.id}, 'cabinet_my')">📋 Подзадачи и детали</button>
                                ${t.status === 'in_progress' ? `
                                    <button class="btn btn-success" onclick="handleDesignerDone(${t.id})">✅ Сдать</button>
                                    <button class="btn btn-danger" onclick="handleDesignerReject(${t.id})">❌ Отказаться</button>
                                ` : ''}
                            </div>
                        </div>
                    `;
                });
                html += `</div>`;
            }

            html += `
                <div class="cab-section-title" style="margin-top: 20px;">
                    <span>🔥 Свободные задачи — можно взять (${availTasks.length})</span>
                </div>
            `;

            if (availTasks.length === 0) {
                html += `<div class="cab-card"><div class="empty-placeholder" style="padding:14px;">Свободных задач сейчас нет</div></div>`;
            } else {
                html += `<div class="cab-cards-list">`;
                availTasks.forEach(t => {
                    html += `
                        <div class="cab-card">
                            <div class="cab-card-header" onclick="openCabinetTaskModal(${t.id}, 'cabinet_available')" style="cursor:pointer;">
                                <h4 class="cab-card-title">#${t.id} — ${escapeHtml(t.theme)}</h4>
                                <span class="status-badge status-pending">В поиске</span>
                            </div>
                            <div class="cab-meta" onclick="openCabinetTaskModal(${t.id}, 'cabinet_available')" style="cursor:pointer;">
                                <span>👤 ${escapeHtml(t.creator_name)}</span>
                                <span>⏰ Дедлайн: <b>${escapeHtml(t.deadline || '—')}</b></span>
                                <span>📐 ${escapeHtml(t.formats)}</span>
                            </div>
                            <div class="action-row">
                                <button class="btn btn-secondary" onclick="openCabinetTaskModal(${t.id}, 'cabinet_available')">👁 Посмотреть ТЗ</button>
                                <button class="btn btn-primary" onclick="handleDesignerTake(${t.id})">💼 Взять в работу</button>
                            </div>
                        </div>
                    `;
                });
                html += `</div>`;
            }

            container.innerHTML = html;
        }

        async function handleDesignerTake(taskId) {
            if (!confirm(`Взять задачу #${taskId} в работу?`)) return;
            try {
                const res = await fetch(`/api/designer/tasks/${taskId}/take`, {
                    method: "POST",
                    headers: apiHeaders()
                });
                const data = await res.json();
                if (!res.ok) {
                    alert(data.error || "Не удалось взять задачу");
                    return;
                }
                closeModal();
                await loadCabinet();
            } catch (e) {
                alert("Ошибка сети: " + e.message);
            }
        }

        async function handleDesignerDone(taskId) {
            const task = (cabinetData.my_tasks || []).find(t => Number(t.id) === Number(taskId));
            const subs = task?.subtasks || [];
            const undoneCount = subs.filter(s => !s.is_done).length;

            if (subs.length > 0 && undoneCount > 0) {
                const ok = confirm(
                    `⚠️ Внимание! Не все подзадачи отмечены выполненными (выполнено ${subs.length - undoneCount} из ${subs.length}).\n\nВсё равно отправить задачу заказчику на проверку?`
                );
                if (!ok) return;
            } else {
                if (!confirm(`Отправить задачу #${taskId} заказчику на проверку?`)) return;
            }

            try {
                const res = await fetch(`/api/designer/tasks/${taskId}/done`, {
                    method: "POST",
                    headers: apiHeaders()
                });
                const data = await res.json();
                if (!res.ok) {
                    alert(data.error || "Ошибка при сдаче задачи");
                    return;
                }
                closeModal();
                await loadCabinet();
            } catch (e) {
                alert("Ошибка сети: " + e.message);
            }
        }

        async function handleDesignerReject(taskId) {
            if (!confirm(`Вы уверены, что хотите отказаться от задачи #${taskId}? Она вернётся в общий чат.`)) return;
            try {
                const res = await fetch(`/api/designer/tasks/${taskId}/reject`, {
                    method: "POST",
                    headers: apiHeaders()
                });
                const data = await res.json();
                if (!res.ok) {
                    alert(data.error || "Ошибка при отказе");
                    return;
                }
                closeModal();
                await loadCabinet();
            } catch (e) {
                alert("Ошибка сети: " + e.message);
            }
        }

        /* Управление подзадачами в модальном окне ЛК */
        function renderModalSubtasks() {
            if (!currentModalTask) return;
            const subs = currentModalTask.subtasks || [];
            const stats = calcSubtaskStats(subs);

            document.getElementById('mSubtaskProgressText').innerText = `${stats.done}/${stats.total} (${stats.pct}%)`;
            document.getElementById('mSubtaskProgressBar').style.width = `${stats.pct}%`;

            const listEl = document.getElementById('mSubtaskList');
            if (subs.length === 0) {
                listEl.innerHTML = '<div style="font-size:11px; color:var(--hint-color);">Пока нет подзадач. Добавьте этапы работы выше ☝️</div>';
                return;
            }

            listEl.innerHTML = '';
            subs.forEach(sub => {
                const item = document.createElement('div');
                item.className = 'subtask-item';

                const left = document.createElement('div');
                left.className = 'subtask-left';

                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.checked = !!sub.is_done;
                cb.onchange = () => handleToggleSubtask(sub.id);

                const span = document.createElement('span');
                span.className = 'subtask-text' + (sub.is_done ? ' done' : '');
                span.innerText = sub.title;

                left.appendChild(cb);
                left.appendChild(span);

                const actions = document.createElement('div');
                actions.className = 'subtask-actions';

                const editBtn = document.createElement('button');
                editBtn.className = 'icon-mini-btn';
                editBtn.innerText = '✏️';
                editBtn.title = 'Редактировать';
                editBtn.onclick = () => handleEditSubtask(sub.id, sub.title);

                const delBtn = document.createElement('button');
                delBtn.className = 'icon-mini-btn';
                delBtn.innerText = '🗑';
                delBtn.title = 'Удалить';
                delBtn.onclick = () => handleDeleteSubtask(sub.id);

                actions.appendChild(editBtn);
                actions.appendChild(delBtn);

                item.appendChild(left);
                item.appendChild(actions);
                listEl.appendChild(item);
            });
        }

        async function handleAddSubtask() {
            if (!currentModalTask) return;
            const input = document.getElementById('newSubtaskInput');
            const title = input.value.trim();
            if (!title) return;

            input.disabled = true;
            try {
                const res = await fetch(`/api/designer/tasks/${currentModalTask.id}/subtasks`, {
                    method: "POST",
                    headers: apiHeaders(),
                    body: JSON.stringify({ title })
                });
                const data = await res.json();
                if (res.ok && data.subtask) {
                    currentModalTask.subtasks = currentModalTask.subtasks || [];
                    currentModalTask.subtasks.push(data.subtask);
                    input.value = '';
                    renderModalSubtasks();
                    renderCabinet();
                } else {
                    alert(data.error || "Ошибка добавления подзадачи");
                }
            } finally {
                input.disabled = false;
                input.focus();
            }
        }

        async function handleToggleSubtask(subtaskId) {
            if (!currentModalTask) return;
            const res = await fetch(`/api/designer/subtasks/${subtaskId}/toggle`, {
                method: "POST",
                headers: apiHeaders()
            });
            if (res.ok) {
                const sub = (currentModalTask.subtasks || []).find(s => s.id === subtaskId);
                if (sub) sub.is_done = !sub.is_done;
                renderModalSubtasks();
                renderCabinet();
            }
        }

        async function handleEditSubtask(subtaskId, oldTitle) {
            const newTitle = prompt("Изменить текст подзадачи:", oldTitle);
            if (!newTitle || !newTitle.trim() || newTitle.trim() === oldTitle) return;

            const res = await fetch(`/api/designer/subtasks/${subtaskId}`, {
                method: "PUT",
                headers: apiHeaders(),
                body: JSON.stringify({ title: newTitle.trim() })
            });
            if (res.ok) {
                const sub = (currentModalTask.subtasks || []).find(s => s.id === subtaskId);
                if (sub) sub.title = newTitle.trim();
                renderModalSubtasks();
            }
        }

        async function handleDeleteSubtask(subtaskId) {
            const res = await fetch(`/api/designer/subtasks/${subtaskId}`, {
                method: "DELETE",
                headers: apiHeaders()
            });
            if (res.ok) {
                currentModalTask.subtasks = (currentModalTask.subtasks || []).filter(s => s.id !== subtaskId);
                renderModalSubtasks();
                renderCabinet();
            }
        }

        async function handleSaveNotes() {
            if (!currentModalTask) return;
            const btn = document.getElementById('saveNotesBtn');
            const notes = document.getElementById('mDesignerNotes').value;
            btn.disabled = true;
            btn.innerText = "⏳ Сохранение...";
            try {
                const res = await fetch(`/api/designer/tasks/${currentModalTask.id}/notes`, {
                    method: "POST",
                    headers: apiHeaders(),
                    body: JSON.stringify({ notes })
                });
                if (res.ok) {
                    currentModalTask.designer_notes = notes;
                    btn.innerText = "✅ Сохранено";
                    renderCabinet();
                    setTimeout(() => { btn.innerText = "💾 Сохранить заметку"; }, 1500);
                } else {
                    alert("Ошибка сохранения заметки");
                    btn.innerText = "💾 Сохранить заметку";
                }
            } finally {
                btn.disabled = false;
            }
        }

        /* Общая таблица задач */
        async function fetchAvailableMonths() {
            try {
                const res = await fetch('/api/months');
                if (res.ok) {
                    const months = await res.json();
                    const monthSelect = document.getElementById('filter-month');
                    const prevVal = monthSelect.value;
                    monthSelect.innerHTML = '<option value="">Последние 2 месяца</option>';
                    months.forEach(ym => {
                        const parts = ym.split('-');
                        const label = monthNames[parseInt(parts[1], 10) - 1] + ' ' + parts[0];
                        const opt = document.createElement('option');
                        opt.value = ym;
                        opt.textContent = label;
                        monthSelect.appendChild(opt);
                    });
                    if (prevVal) monthSelect.value = prevVal;
                }
            } catch(e) {}
        }

        async function loadTasks(month = '') {
            document.getElementById('tasks-container').innerHTML = '<div class="empty-placeholder">Загрузка задач...</div>';
            try {
                const url = month ? `/api/tasks?month=${encodeURIComponent(month)}` : '/api/tasks';
                const response = await fetch(url);
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                allTasks = await response.json();
                populateDropdowns();
                renderTasks();
            } catch (err) {
                document.getElementById('tasks-container').innerHTML = 
                    `<div class="empty-placeholder" style="color: #d9534f;">⚠️ Ошибка загрузки:<br><code>${escapeHtml(err.message)}</code></div>`;
            }
        }

        async function refreshAll() {
            const btn = document.getElementById('refreshBtn');
            btn.disabled = true;
            btn.innerText = '⏳ Обновление...';
            try {
                if (activeTab === 'cabinet') {
                    await loadCabinet();
                } else {
                    await fetchAvailableMonths();
                    const selectedMonth = document.getElementById('filter-month').value;
                    await loadTasks(selectedMonth);
                }
            } finally {
                btn.disabled = false;
                btn.innerText = '🔄 Обновить';
            }
        }

        function populateDropdowns() {
            const creatorSelect = document.getElementById('filter-creator');
            const designerSelect = document.getElementById('filter-designer');
            const prevCreator = creatorSelect.value;
            const prevDesigner = designerSelect.value;

            const creators = new Set();
            const designers = new Set();
            allTasks.forEach(t => {
                if (t.creator_name) creators.add(t.creator_name);
                if (t.designer_name) designers.add(t.designer_name);
            });

            creatorSelect.innerHTML = '<option value="">Все заказчики</option>';
            creators.forEach(name => {
                const opt = document.createElement('option');
                opt.value = name; opt.textContent = name;
                creatorSelect.appendChild(opt);
            });
            if (prevCreator && creators.has(prevCreator)) creatorSelect.value = prevCreator;

            designerSelect.innerHTML = '<option value="">Все дизайнеры</option>';
            designers.forEach(name => {
                const opt = document.createElement('option');
                opt.value = name; opt.textContent = name;
                designerSelect.appendChild(opt);
            });
            if (prevDesigner && designers.has(prevDesigner)) designerSelect.value = prevDesigner;
        }

        function getMonthYearKey(dateStr) {
            if (!dateStr) return "Без даты";
            const clean = dateStr.replace("T", " ");
            const datePart = clean.split(" ")[0];
            if (datePart.includes("-")) {
                const parts = datePart.split("-");
                if (parts.length === 3) {
                    return `${monthNames[parseInt(parts[1], 10) - 1]} ${parts[0]}`;
                }
            }
            if (datePart.includes(".")) {
                const parts = datePart.split(".");
                if (parts.length === 3) {
                    return `${monthNames[parseInt(parts[1], 10) - 1]} ${parts[2]}`;
                }
            }
            return "Без даты";
        }

        function getDeadlineFlag(task) {
            if (!task) return '<span class="sla-pending">—</span>';
            if (task.status === "canceled") return '<span class="sla-pending">⚪ Отменена</span>';
            if (!task.deadline_dt) {
                return task.status === "completed" ? '<span class="sla-ontime">🟢 Завершена</span>' : '<span class="sla-pending">—</span>';
            }
            const deadlineTime = new Date(task.deadline_dt).getTime();
            if (task.status === "completed") {
                if (task.completed_at) {
                    const doneTime = new Date(task.completed_at.replace(" ", "T")).getTime();
                    if (!isNaN(doneTime) && doneTime <= deadlineTime) return '<span class="sla-ontime">🟢 В срок</span>';
                    if (!isNaN(doneTime) && doneTime > deadlineTime) return '<span class="sla-overdue">🔴 Просрочена</span>';
                }
                return '<span class="sla-ontime">🟢 В срок</span>';
            }
            return new Date().getTime() > deadlineTime ? '<span class="sla-overdue">🔴 Просрочена</span>' : '<span class="sla-pending">🟡 В процессе</span>';
        }

        function renderTasks() {
            const creatorFilter = document.getElementById('filter-creator').value;
            const designerFilter = document.getElementById('filter-designer').value;
            const searchFilter = document.getElementById('filter-search').value.toLowerCase().trim();

            const filtered = allTasks.filter(task => {
                if (creatorFilter && task.creator_name !== creatorFilter) return false;
                if (designerFilter && task.designer_name !== designerFilter) return false;
                if (searchFilter && !task.theme.toLowerCase().includes(searchFilter)) return false;

                if (currentStatusFilter === "ACTIVE_ONLY") {
                    if (!["pending", "in_progress", "awaiting_confirmation"].includes(task.status)) return false;
                } else if (currentStatusFilter && task.status !== currentStatusFilter) {
                    return false;
                }
                return true;
            });

            const container = document.getElementById('tasks-container');
            if (filtered.length === 0) {
                container.innerHTML = '<div class="empty-placeholder">Задачи не найдены</div>';
                return;
            }

            const groups = {};
            filtered.forEach(task => {
                const key = getMonthYearKey(task.created_at);
                if (!groups[key]) groups[key] = [];
                groups[key].push(task);
            });

            let html = '';
            for (const [monthKey, tasks] of Object.entries(groups)) {
                html += `
                    <div class="month-section">
                        <div class="month-header">
                            <span>📅 ${monthKey}</span>
                            <span class="month-count">${tasks.length} задач</span>
                        </div>
                        <div class="task-table-container">
                            <table class="main-table">
                                <thead>
                                    <tr>
                                        <th>№</th>
                                        <th>Тема</th>
                                        <th>Создана</th>
                                        <th>Заказчик</th>
                                        <th>Дизайнер</th>
                                        <th>Дедлайн</th>
                                        <th>Срок</th>
                                        <th>Статус</th>
                                    </tr>
                                </thead>
                                <tbody>
                `;
                tasks.forEach(t => {
                    const st = statusMap[t.status] || { text: t.status, class: "status-awaiting_confirmation" };
                    const createdAt = t.created_at ? t.created_at.slice(0, 16) : '—';

                    html += `
                        <tr onclick="openTaskModal(${t.id})">
                            <td class="task-id">#${t.id}</td>
                            <td class="task-theme" title="${escapeHtml(t.theme)}">${escapeHtml(t.theme)}</td>
                            <td class="task-date">${createdAt}</td>
                            <td>${escapeHtml(t.creator_name)}</td>
                            <td>${escapeHtml(t.designer_name || '—')}</td>
                            <td>${escapeHtml(t.deadline || '—')}</td>
                            <td>${getDeadlineFlag(t)}</td>
                            <td><span class="status-badge ${st.class}">${st.text}</span></td>
                        </tr>
                    `;
                });
                html += `</tbody></table></div></div>`;
            }
            container.innerHTML = html;
        }

        document.querySelectorAll('.chip-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.chip-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                currentStatusFilter = this.getAttribute('data-status');
                renderTasks();
            });
        });

        function openTaskModal(taskId) {
            const task = allTasks.find(t => Number(t.id) === Number(taskId));
            if (!task) return;
            renderModalWithTask(task, 'readonly');
        }

        function openCabinetTaskModal(taskId, mode) {
            const pool = mode === 'cabinet_my' ? cabinetData.my_tasks : cabinetData.available_tasks;
            const task = (pool || []).find(t => Number(t.id) === Number(taskId));
            if (!task) return;
            renderModalWithTask(task, mode);
        }

        function renderModalWithTask(task, mode) {
            currentModalTask = task;
            currentModalMode = mode;

            const st = statusMap[task.status] || { text: task.status || "—", class: "status-awaiting_confirmation" };
            document.getElementById('mTaskTitle').innerText = `Задача #${task.id}`;
            document.getElementById('mTheme').innerText = task.theme || '—';
            document.getElementById('mFormats').innerText = task.formats || '—';
            document.getElementById('mCreatedAt').innerText = task.created_at || '—';
            document.getElementById('mCreator').innerText = (task.creator_name || 'Не указан') + (task.creator_position ? ` (${task.creator_position})` : '');
            document.getElementById('mDesigner').innerText = task.designer_name || 'Не назначен';

            let datesInfo = `<b>Дедлайн:</b> ${escapeHtml(task.deadline || '—')}`;
            if (task.completed_at) datesInfo += ` | <b>Завершена:</b> ${escapeHtml(task.completed_at)}`;
            document.getElementById('mStatusSla').innerHTML = `<span class="status-badge ${st.class}">${st.text}</span> &nbsp; ${datesInfo} &nbsp; ${getDeadlineFlag(task)}`;
            document.getElementById('mDescription').innerText = task.description || 'ТЗ отсутствует';

            // Управление видимостью секций ЛК дизайнера
            const wsSection = document.getElementById('designerWorkspaceSection');
            const takeSection = document.getElementById('designerTakeSection');

            if (mode === 'cabinet_my') {
                wsSection.style.display = 'flex';
                takeSection.style.display = 'none';
                document.getElementById('mDesignerNotes').value = task.designer_notes || '';
                renderModalSubtasks();

                const ctrlRow = document.getElementById('mDesignerControlButtons');
                if (task.status === 'in_progress') {
                    ctrlRow.innerHTML = `
                        <button class="btn btn-success" onclick="handleDesignerDone(${task.id})">✅ Сдать на проверку</button>
                        <button class="btn btn-danger" onclick="handleDesignerReject(${task.id})">❌ Отказаться</button>
                    `;
                } else {
                    ctrlRow.innerHTML = `<div style="font-size:12px; color:var(--hint-color);">⏳ Задача отправлена заказчику и ожидает подтверждения.</div>`;
                }
            } else if (mode === 'cabinet_available') {
                wsSection.style.display = 'none';
                takeSection.style.display = 'block';
                document.getElementById('mTakeTaskBtn').onclick = () => handleDesignerTake(task.id);
            } else {
                wsSection.style.display = 'none';
                takeSection.style.display = 'none';
            }

            // Вложения
            const attachments = task.attachments || [];
            const imageItems = [];
            const otherFiles = [];

            if (attachments.length > 0) {
                attachments.forEach(att => {
                    if (isImageAttachment(att)) imageItems.push(att);
                    else otherFiles.push(att);
                });
            } else {
                (task.reference_photos || []).forEach(fid => imageItems.push({ file_id: fid, file_type: 'photo' }));
                (task.reference_docs || []).forEach((fid, i) => otherFiles.push({ file_id: fid, file_type: 'doc', file_name: `Файл #${i + 1}` }));
            }

            const parts = [];
            if (imageItems.length > 0) parts.push(`Изображения: ${imageItems.length} шт.`);
            if (otherFiles.length > 0) parts.push(`Файлы: ${otherFiles.length} шт.`);

            let refText = 'Отсутствуют';
            if (parts.length > 0) {
                refText = parts.join(', ');
                if (task.reference_data) refText += ` | Ссылки: ${task.reference_data}`;
            } else if (task.reference_data) {
                refText = task.reference_data;
            }
            document.getElementById('mReferencesText').innerText = refText;

            const galleryContainer = document.getElementById('mPhotoGallery');
            galleryContainer.innerHTML = '';
            imageItems.forEach((item, idx) => {
                const wrapper = document.createElement('div');
                wrapper.className = 'gallery-item';

                const img = document.createElement('img');
                img.className = 'gallery-thumb';
                img.src = `/api/file/${encodeURIComponent(item.file_id)}`;
                img.alt = item.file_name || `Референс #${idx + 1}`;
                img.loading = 'lazy';
                img.title = 'Нажмите, чтобы развернуть/свернуть';
                img.onclick = () => wrapper.classList.toggle('expanded');

                const dlLink = document.createElement('a');
                dlLink.className = 'img-download-link';
                dlLink.href = `/api/file/${encodeURIComponent(item.file_id)}?download=1`;
                dlLink.target = '_blank';
                dlLink.rel = 'noopener';
                dlLink.innerText = '⬇️ Скачать';

                wrapper.appendChild(img);
                wrapper.appendChild(dlLink);
                galleryContainer.appendChild(wrapper);
            });

            const filesContainer = document.getElementById('mFilesList');
            filesContainer.innerHTML = '';
            otherFiles.forEach((item, idx) => {
                const link = document.createElement('a');
                link.className = 'file-download-btn';
                link.href = `/api/file/${encodeURIComponent(item.file_id)}?download=1`;
                link.target = '_blank';
                link.rel = 'noopener';
                const label = item.file_name || `Документ #${idx + 1}`;
                link.innerHTML = `<span>📄 ${escapeHtml(label)}</span><span>⬇️ Скачать</span>`;
                filesContainer.appendChild(link);
            });

            document.getElementById('taskModal').style.display = 'flex';
        }

        function closeModal() {
            document.getElementById('taskModal').style.display = 'none';
            currentModalTask = null;
        }
        function closeModalOnOverlay(e) { if (e.target.id === 'taskModal') closeModal(); }

        document.getElementById('filter-month').addEventListener('change', (e) => loadTasks(e.target.value));
        document.getElementById('filter-creator').addEventListener('change', renderTasks);
        document.getElementById('filter-designer').addEventListener('change', renderTasks);
        document.getElementById('filter-search').addEventListener('input', renderTasks);

        (async function bootstrap() {
            await initUserProfile();
            await fetchAvailableMonths();
            await loadTasks();
        })();
    </script>
</body>
</html>
"""


async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=HTML_CONTENT, content_type='text/html')


async def handle_me(request: web.Request) -> web.Response:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    tg_user = verify_telegram_webapp_user(init_data)
    if not tg_user or "id" not in tg_user:
        return web.json_response({"is_designer": False, "is_admin": False})

    user_id = int(tg_user["id"])
    db_user = await db.get_user(user_id)
    is_des = bool(db_user and is_designer_position(db_user[2]))
    is_adm = config.is_admin(user_id)
    return web.json_response({
        "user_id": user_id,
        "full_name": db_user[1] if db_user else tg_user.get("first_name", ""),
        "is_designer": is_des,
        "is_admin": is_adm,
    })


async def handle_designer_cabinet(request: web.Request) -> web.Response:
    designer, err_resp = await get_authenticated_designer(request)
    if err_resp:
        return err_resp

    data = await db.get_designer_cabinet_data(designer["user_id"])
    return web.json_response(data)


async def handle_designer_take(request: web.Request) -> web.Response:
    designer, err_resp = await get_authenticated_designer(request)
    if err_resp:
        return err_resp

    task_id = int(request.match_info["task_id"])
    bot: Bot = request.app["bot"]
    ok, msg = await execute_designer_take_task(bot, task_id, designer["user_id"], designer.get("username"))
    if not ok:
        return web.json_response({"error": msg}, status=400)
    return web.json_response({"ok": True, "message": msg})


async def handle_designer_done(request: web.Request) -> web.Response:
    designer, err_resp = await get_authenticated_designer(request)
    if err_resp:
        return err_resp

    task_id = int(request.match_info["task_id"])
    bot: Bot = request.app["bot"]
    ok, msg = await execute_designer_done_task(bot, task_id, designer["user_id"], notify_designer_pm=True)
    if not ok:
        return web.json_response({"error": msg}, status=400)
    return web.json_response({"ok": True, "message": msg})


async def handle_designer_reject(request: web.Request) -> web.Response:
    designer, err_resp = await get_authenticated_designer(request)
    if err_resp:
        return err_resp

    task_id = int(request.match_info["task_id"])
    bot: Bot = request.app["bot"]
    ok, msg = await execute_designer_reject_task(bot, task_id, designer["user_id"], notify_designer_pm=True)
    if not ok:
        return web.json_response({"error": msg}, status=400)
    return web.json_response({"ok": True, "message": msg})


async def handle_add_subtask(request: web.Request) -> web.Response:
    designer, err_resp = await get_authenticated_designer(request)
    if err_resp:
        return err_resp

    task_id = int(request.match_info["task_id"])
    task = await db.get_task(task_id)
    if not task or task["designer_id"] != designer["user_id"]:
        return web.json_response({"error": "Нет доступа к этой задаче."}, status=403)

    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        return web.json_response({"error": "Название подзадачи не может быть пустым."}, status=400)

    subtask = await db.add_task_subtask(task_id, designer["user_id"], title)
    return web.json_response({"ok": True, "subtask": subtask})


async def handle_toggle_subtask(request: web.Request) -> web.Response:
    designer, err_resp = await get_authenticated_designer(request)
    if err_resp:
        return err_resp

    subtask_id = int(request.match_info["subtask_id"])
    ok = await db.toggle_task_subtask(subtask_id, designer["user_id"])
    if not ok:
        return web.json_response({"error": "Подзадача не найдена."}, status=404)
    return web.json_response({"ok": True})


async def handle_edit_subtask(request: web.Request) -> web.Response:
    designer, err_resp = await get_authenticated_designer(request)
    if err_resp:
        return err_resp

    subtask_id = int(request.match_info["subtask_id"])
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        return web.json_response({"error": "Пустое название."}, status=400)

    ok = await db.update_task_subtask_title(subtask_id, designer["user_id"], title)
    if not ok:
        return web.json_response({"error": "Подзадача не найдена."}, status=404)
    return web.json_response({"ok": True})


async def handle_delete_subtask(request: web.Request) -> web.Response:
    designer, err_resp = await get_authenticated_designer(request)
    if err_resp:
        return err_resp

    subtask_id = int(request.match_info["subtask_id"])
    ok = await db.delete_task_subtask(subtask_id, designer["user_id"])
    if not ok:
        return web.json_response({"error": "Подзадача не найдена."}, status=404)
    return web.json_response({"ok": True})


async def handle_save_notes(request: web.Request) -> web.Response:
    designer, err_resp = await get_authenticated_designer(request)
    if err_resp:
        return err_resp

    task_id = int(request.match_info["task_id"])
    body = await request.json()
    notes = body.get("notes") or ""
    ok = await db.update_designer_task_notes(task_id, designer["user_id"], notes)
    if not ok:
        return web.json_response({"error": "Задача не найдена."}, status=404)
    return web.json_response({"ok": True})


async def handle_file_proxy(request: web.Request) -> web.StreamResponse:
    file_id = request.match_info.get("file_id")
    if not file_id:
        return web.Response(status=400, text="file_id required")

    force_download = request.query.get("download") == "1"
    bot: Bot = request.app["bot"]

    try:
        att_info = await db.get_attachment_info(file_id)
        tg_file = await bot.get_file(file_id)
        if not tg_file.file_path:
            return web.Response(status=404, text="File path not found")

        file_name = (att_info.get("file_name") if att_info else None) or os.path.basename(tg_file.file_path)
        guessed_type, _ = mimetypes.guess_type(file_name)
        content_type = guessed_type or "application/octet-stream"

        stream = io.BytesIO()
        await bot.download_file(tg_file.file_path, destination=stream)
        stream.seek(0)

        headers = {
            "Content-Type": content_type,
            "Cache-Control": "public, max-age=86400"
        }
        if force_download:
            encoded_name = quote(file_name)
            headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_name}"

        return web.Response(body=stream.read(), headers=headers)
    except Exception as e:
        logger.error(f"Ошибка получения файла {file_id}: {e}")
        return web.Response(status=500, text="Failed to fetch file")


async def handle_api_months(request: web.Request) -> web.Response:
    months = await db.get_available_task_months()
    return web.json_response(months)


async def handle_api_tasks(request: web.Request) -> web.Response:
    month_param = request.query.get("month")
    tasks = await db.get_tasks_for_webapp(month_filter=month_param)
    return web.json_response(tasks)


def create_webapp_app(bot: Bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get('/', handle_index)
    app.router.add_get('/api/me', handle_me)
    app.router.add_get('/api/tasks', handle_api_tasks)
    app.router.add_get('/api/months', handle_api_months)
    app.router.add_get('/api/photo/{file_id}', handle_file_proxy)
    app.router.add_get('/api/file/{file_id}', handle_file_proxy)

    # API Личного кабинета дизайнера
    app.router.add_get('/api/designer/cabinet', handle_designer_cabinet)
    app.router.add_post('/api/designer/tasks/{task_id}/take', handle_designer_take)
    app.router.add_post('/api/designer/tasks/{task_id}/done', handle_designer_done)
    app.router.add_post('/api/designer/tasks/{task_id}/reject', handle_designer_reject)
    app.router.add_post('/api/designer/tasks/{task_id}/subtasks', handle_add_subtask)
    app.router.add_post('/api/designer/subtasks/{subtask_id}/toggle', handle_toggle_subtask)
    app.router.add_put('/api/designer/subtasks/{subtask_id}', handle_edit_subtask)
    app.router.add_delete('/api/designer/subtasks/{subtask_id}', handle_delete_subtask)
    app.router.add_post('/api/designer/tasks/{task_id}/notes', handle_save_notes)
    return app