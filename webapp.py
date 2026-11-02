import io
import json
import logging
from aiohttp import web
from aiogram import Bot
import database as db

logger = logging.getLogger(__name__)

HTML_CONTENT = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Список задач</title>
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

        h2 {
            margin: 0 0 12px 0;
            font-size: 20px;
            text-align: center;
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

        .filter-row {
            display: flex;
            gap: 8px;
        }

        .filter-group {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .filter-group label {
            font-size: 11px;
            font-weight: 600;
            color: var(--hint-color);
            text-transform: uppercase;
        }

        select, input {
            width: 100%;
            padding: 8px 10px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            background-color: var(--bg-color);
            color: var(--text-color);
            font-size: 13px;
            outline: none;
            box-sizing: border-box;
        }

        .status-buttons-container {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

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
            transition: all 0.15s ease;
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
        .chip-active-group.active {
            background-color: var(--link-color);
            color: #fff;
        }

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
        tbody tr { cursor: pointer; transition: background-color 0.15s ease; }
        tbody tr:hover { background-color: rgba(0, 122, 255, 0.06); }
        tr:last-child td { border-bottom: none; }

        .task-id { font-weight: 700; color: var(--hint-color); }
        .task-theme { font-weight: 600; max-width: 160px; overflow: hidden; text-overflow: ellipsis; }
        .task-date { color: var(--hint-color); font-size: 11px; }

        .status-badge { display: inline-block; padding: 2px 5px; border-radius: 5px; font-size: 11px; font-weight: 600; }
        .status-pending { background-color: #fff3cd; color: #856404; }
        .status-in_progress { background-color: #cce5ff; color: #004085; }
        .status-awaiting_confirmation { background-color: #e2e3e5; color: #383d41; }
        .status-completed { background-color: #d4edda; color: #155724; }
        .status-canceled { background-color: #f8d7da; color: #721c24; }

        .sla-ontime { color: #28a745; font-weight: 600; }
        .sla-overdue { color: #dc3545; font-weight: 600; }
        .sla-pending { color: #ffc107; font-weight: 600; }
        .empty-placeholder { text-align: center; padding: 30px; color: var(--hint-color); font-size: 14px; }

        /* Модальное окно */
        .modal-overlay {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background-color: rgba(0, 0, 0, 0.45);
            display: none; justify-content: center; align-items: center;
            z-index: 1000; padding: 12px; box-sizing: border-box; backdrop-filter: blur(2px);
        }

        .modal-card {
            background-color: var(--card-bg); color: var(--text-color);
            width: 100%; max-width: 500px; max-height: 90vh;
            border-radius: 14px; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
            display: flex; flex-direction: column; overflow: hidden;
            animation: modalFadeIn 0.2s ease-out;
        }

        @keyframes modalFadeIn {
            from { opacity: 0; transform: translateY(10px) scale(0.98); }
            to { opacity: 1; transform: translateY(0) scale(1); }
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

        /* Компактная таблица основной информации */
        .modal-info-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            background-color: var(--bg-color);
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }

        .modal-info-table td {
            padding: 5px 8px;
            border-bottom: 1px solid var(--border-color);
            vertical-align: middle;
        }

        .modal-info-table tr:last-child td {
            border-bottom: none;
        }

        .modal-info-table .info-label {
            width: 110px;
            font-size: 11px;
            font-weight: 700;
            color: var(--hint-color);
            text-transform: uppercase;
            white-space: nowrap;
        }

        .modal-info-table .info-val {
            font-weight: 500;
            word-break: break-word;
        }

        .modal-field { display: flex; flex-direction: column; gap: 3px; }
        .modal-label { font-size: 11px; text-transform: uppercase; font-weight: 700; color: var(--hint-color); }
        .modal-value { font-weight: 500; word-break: break-word; }

        .modal-desc-box {
            background-color: var(--bg-color); border: 1px solid var(--border-color);
            border-radius: 8px; padding: 8px 10px; max-height: 140px; overflow-y: auto;
            white-space: pre-wrap; font-family: inherit; font-size: 12px;
        }

        .photo-gallery { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
        .gallery-thumb {
            width: 60px; height: 60px; object-fit: cover; border-radius: 6px;
            cursor: pointer; border: 1px solid var(--border-color);
            transition: all 0.25s ease-in-out; background-color: var(--bg-color);
            flex-shrink: 0;
        }
        .gallery-thumb.expanded {
            width: 100% !important; height: auto !important; max-height: 440px;
            object-fit: contain; border: 1px solid var(--link-color);
        }
    </style>
</head>
<body>
    <div id="mainAppContent">
        <h2>📋 Список задач</h2>

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

    <!-- Модальное окно -->
    <div class="modal-overlay" id="taskModal" onclick="closeModalOnOverlay(event)">
        <div class="modal-card">
            <div class="modal-header">
                <h3 class="modal-title" id="mTaskTitle">Задача #0</h3>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body">
                <!-- Таблица основной информации задачи -->
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

                <!-- ТЗ и материалы -->
                <div class="modal-field">
                    <span class="modal-label">Техническое задание (ТЗ)</span>
                    <div class="modal-desc-box" id="mDescription"></div>
                </div>
                <div class="modal-field">
                    <span class="modal-label">Референсы / Вложения</span>
                    <span class="modal-value" id="mReferencesText"></span>
                    <div class="photo-gallery" id="mPhotoGallery"></div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const tg = window.Telegram?.WebApp;
        if (tg) { tg.expand(); tg.ready(); }

        let allTasks = [];
        let currentStatusFilter = "";

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

        async function fetchAvailableMonths() {
            try {
                const res = await fetch('/api/months');
                if (res.ok) {
                    const months = await res.json();
                    const monthSelect = document.getElementById('filter-month');
                    months.forEach(ym => {
                        const parts = ym.split('-');
                        const label = monthNames[parseInt(parts[1], 10) - 1] + ' ' + parts[0];
                        const opt = document.createElement('option');
                        opt.value = ym;
                        opt.textContent = label;
                        monthSelect.appendChild(opt);
                    });
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
                    `<div class="empty-placeholder" style="color: #d9534f;">⚠️ Ошибка загрузки:<br><code>${err.message}</code></div>`;
            }
        }

        function populateDropdowns() {
            const creators = new Set();
            const designers = new Set();
            allTasks.forEach(t => {
                if (t.creator_name) creators.add(t.creator_name);
                if (t.designer_name) designers.add(t.designer_name);
            });

            const creatorSelect = document.getElementById('filter-creator');
            creatorSelect.innerHTML = '<option value="">Все заказчики</option>';
            creators.forEach(name => {
                const opt = document.createElement('option');
                opt.value = name; opt.textContent = name;
                creatorSelect.appendChild(opt);
            });

            const designerSelect = document.getElementById('filter-designer');
            designerSelect.innerHTML = '<option value="">Все дизайнеры</option>';
            designers.forEach(name => {
                const opt = document.createElement('option');
                opt.value = name; opt.textContent = name;
                designerSelect.appendChild(opt);
            });
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
                            <td class="task-theme" title="${t.theme}">${t.theme}</td>
                            <td class="task-date">${createdAt}</td>
                            <td>${t.creator_name}</td>
                            <td>${t.designer_name || '—'}</td>
                            <td>${t.deadline || '—'}</td>
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

        function toggleImageExpand(imgElement) {
            imgElement.classList.toggle('expanded');
        }

        function openTaskModal(taskId) {
            const task = allTasks.find(t => Number(t.id) === Number(taskId));
            if (!task) return;

            const st = statusMap[task.status] || { text: task.status || "—", class: "status-awaiting_confirmation" };
            document.getElementById('mTaskTitle').innerText = `Задача #${task.id}`;
            document.getElementById('mTheme').innerText = task.theme || '—';
            document.getElementById('mFormats').innerText = task.formats || '—';
            document.getElementById('mCreatedAt').innerText = task.created_at || '—';
            document.getElementById('mCreator').innerText = (task.creator_name || 'Не указан') + (task.creator_position ? ` (${task.creator_position})` : '');
            document.getElementById('mDesigner').innerText = task.designer_name || 'Не назначен';

            let datesInfo = `<b>Дедлайн:</b> ${task.deadline || '—'}`;
            if (task.completed_at) datesInfo += ` | <b>Завершена:</b> ${task.completed_at}`;
            document.getElementById('mStatusSla').innerHTML = `<span class="status-badge ${st.class}">${st.text}</span> &nbsp; ${datesInfo} &nbsp; ${getDeadlineFlag(task)}`;
            document.getElementById('mDescription').innerText = task.description || 'ТЗ отсутствует';

            const photos = task.reference_photos || [];
            const docs = task.reference_docs || [];
            const parts = [];
            if (photos.length > 0) parts.push(`Фото: ${photos.length} шт.`);
            if (docs.length > 0) parts.push(`Файлы: ${docs.length} шт.`);

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
            photos.forEach(fid => {
                const img = document.createElement('img');
                img.className = 'gallery-thumb';
                img.src = `/api/photo/${encodeURIComponent(fid)}`;
                img.alt = 'Референс';
                img.loading = 'lazy';
                img.title = 'Нажмите, чтобы развернуть/свернуть';
                img.onclick = () => toggleImageExpand(img);
                galleryContainer.appendChild(img);
            });

            document.getElementById('taskModal').style.display = 'flex';
        }

        function closeModal() { document.getElementById('taskModal').style.display = 'none'; }
        function closeModalOnOverlay(e) { if (e.target.id === 'taskModal') closeModal(); }

        document.getElementById('filter-month').addEventListener('change', (e) => loadTasks(e.target.value));
        document.getElementById('filter-creator').addEventListener('change', renderTasks);
        document.getElementById('filter-designer').addEventListener('change', renderTasks);
        document.getElementById('filter-search').addEventListener('input', renderTasks);

        fetchAvailableMonths();
        loadTasks();
    </script>
</body>
</html>
"""


async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=HTML_CONTENT, content_type='text/html')


async def handle_photo_proxy(request: web.Request) -> web.StreamResponse:
    file_id = request.match_info.get("file_id")
    if not file_id:
        return web.Response(status=400, text="file_id required")

    bot: Bot = request.app["bot"]
    try:
        tg_file = await bot.get_file(file_id)
        if not tg_file.file_path:
            return web.Response(status=404, text="File path not found")

        stream = io.BytesIO()
        await bot.download_file(tg_file.file_path, destination=stream)
        stream.seek(0)
        return web.Response(body=stream.read(), headers={
            "Content-Type": "image/jpeg",
            "Cache-Control": "public, max-age=86400"
        })
    except Exception as e:
        logger.error(f"Ошибка получения фото {file_id}: {e}")
        return web.Response(status=500, text="Failed to fetch image")


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
    app.router.add_get('/api/tasks', handle_api_tasks)
    app.router.add_get('/api/months', handle_api_months)
    app.router.add_get('/api/photo/{file_id}', handle_photo_proxy)
    return app