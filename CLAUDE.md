# Fleet Server — Міграція Web UI на AdminLTE v4

## Контекст проекту

Fleet Server — внутрішній дашборд телеметрії автопарку (~10 авто).
Поточний Web UI: FastAPI + Jinja2 + Tailwind CSS + HTMX.
Мета: повна заміна Tailwind на AdminLTE v4 (Bootstrap 5).

**Стек, який НЕ змінюється:**
- FastAPI + Jinja2 (серверний рендеринг)
- HTMX (партіальні оновлення)
- Вся Python-логіка в `api/routes/web.py`
- Всі URL маршрути та форми

---

## Крок 1 — Завантажити AdminLTE v4

```bash
# Перейти до директорії проекту
cd web/static

# Завантажити AdminLTE v4 через npm або CDN
# Варіант A: npm (рекомендовано)
npm init -y
npm install admin-lte@^4

# Скопіювати dist файли
cp -r node_modules/admin-lte/dist ./adminlte
cp -r node_modules/bootstrap/dist/js ./adminlte/js/bootstrap

# Варіант B: пряме завантаження
# https://github.com/ColorlibHQ/AdminLTE/releases/latest
# Розпакувати dist/ → web/static/adminlte/
```

Після цього структура має бути:
```
web/static/
└── adminlte/
    ├── css/
    │   └── adminlte.min.css
    └── js/
        └── adminlte.min.js
```

---

## Крок 2 — Оновити `base.html`

Замінити весь вміст `web/templates/base.html`. Вимоги:

**HEAD:**
```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.min.css">
<link rel="stylesheet" href="/static/adminlte/css/adminlte.min.css">
```

**Структура body (AdminLTE v4 layout):**
```
body.layout-fixed
└── div.app-wrapper
    ├── nav.app-header (топ-навбар)
    ├── aside.app-sidebar (ліва панель)
    └── main.app-main
        └── div.app-content
            └── div.container-fluid
                └── {% block content %}
```

**Навбар (`.app-header`):**
- Зліва: кнопка `data-lte-toggle="sidebar"` + логотип "🚛 Fleet"
- Справа: ім'я користувача → `user.full_name or user.email`
- Справа: бейдж `superuser` якщо `user.role == 'superuser'`
- Справа: посилання "Вийти" → `/logout`

**Sidebar (`.app-sidebar`):**
- Лого: "🚛 Fleet"
- Меню item "Автопарк" → `/fleet`, іконка `bi-truck`
- Меню item "Адмін" → `/admin` (тільки якщо `user.role == 'superuser'`), іконка `bi-gear`
- Активний пункт: `{% if active == 'fleet' %}active{% endif %}`

**Підключити скрипти перед `</body>`:**
```html
<script src="https://unpkg.com/htmx.org@1.9.12"></script>
<script src="/static/adminlte/js/adminlte.min.js"></script>
{% block scripts %}{% endblock %}
```

---

## Крок 3 — Оновити `login.html`

`login.html` — standalone сторінка (без `base.html`), потребує окремого Bootstrap підключення.

**Структура:**
```html
<!DOCTYPE html>
<html>
<head>
  <!-- Bootstrap 5 + AdminLTE CSS -->
</head>
<body class="login-page bg-body-secondary">
  <div class="login-box">
    <div class="card card-outline card-primary">
      <div class="card-header text-center">
        <h1>🚛 Fleet Server</h1>
      </div>
      <div class="card-body">
        <!-- Tabs: Вхід / Реєстрація -->
        <ul class="nav nav-pills">
          <li><a href="/login">Вхід</a></li>
          <li><a href="/register">Реєстрація</a></li>
        </ul>

        <!-- Alert для error -->
        <!-- Alert для msg -->

        <!-- Форма login або register -->
      </div>
    </div>
  </div>
</body>
```

**Форма login:**
- `input-group` з іконкою `bi-envelope` для email
- `input-group` з іконкою `bi-lock` для password
- Кнопка `btn btn-primary w-100` "Увійти"

**Форма register:**
- email, full_name, password
- Текст під кнопкою: "Акаунт буде активовано адміністратором"

---

## Крок 4 — Оновити `fleet.html`

**Заголовок сторінки:**
```html
<div class="app-content-header">
  <div class="container-fluid">
    <h3 class="mb-0">Автопарк</h3>
    <small class="text-muted">
      <i class="bi bi-circle-fill text-success" style="font-size:.5rem"></i>
      Оновлення кожні 30 сек
    </small>
  </div>
</div>
```

**Порожній стан (немає авто):**
```html
<div class="card">
  <div class="card-body text-center py-5">
    <i class="bi bi-truck fs-1 text-muted"></i>
    <p class="text-muted mt-2">Авто не призначені.</p>
    <!-- посилання на /admin?tab=vehicles для superuser -->
  </div>
</div>
```

**Grid авто (замість Tailwind grid):**
```html
<div id="fleet-grid" class="row g-3"
     hx-get="/partials/fleet"
     hx-trigger="every 30s"
     hx-target="#fleet-grid"
     hx-swap="outerHTML">
  {% include "partials/fleet_cards.html" %}
</div>
```

---

## Крок 5 — Оновити `partials/fleet_cards.html`

Кожна картка авто → Bootstrap card у `col-md-6 col-xl-4`:

```html
{% for v in vehicles %}
<div class="col-md-6 col-xl-4">
  <a href="/vehicles/{{ v.id }}" class="text-decoration-none">
    <div class="card h-100 card-outline card-primary border-hover">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-start">
          <div>
            <h5 class="card-title mb-0">{{ v.name }}</h5>
            <code class="text-muted small">{{ v.vpn_ip }}</code>
          </div>
          <!-- Badge online/offline -->
          {% if v.online %}
          <span class="badge bg-success"><i class="bi bi-circle-fill me-1"></i>Online</span>
          {% else %}
          <span class="badge bg-secondary">Offline</span>
          {% endif %}
        </div>
      </div>
      <div class="card-footer d-flex justify-content-between text-muted small">
        <span>
          {% if v.last_seen_at %}
            {{ v.last_seen_at.strftime('%d.%m %H:%M') }}
          {% else %}
            Ще не з'єднувалось
          {% endif %}
        </span>
        <!-- sync badge -->
        {% if v.sync_status == 'ok' %}
        <span class="text-success">sync: ok</span>
        {% elif v.sync_status == 'error' %}
        <span class="text-danger">sync: error</span>
        {% elif v.sync_status == 'timeout' %}
        <span class="text-warning">sync: timeout</span>
        {% else %}
        <span class="text-muted">sync: {{ v.sync_status }}</span>
        {% endif %}
      </div>
    </div>
  </a>
</div>
{% endfor %}
```

---

## Крок 6 — Оновити `vehicle.html`

**Breadcrumb:**
```html
<div class="app-content-header">
  <ol class="breadcrumb">
    <li class="breadcrumb-item"><a href="/fleet">Автопарк</a></li>
    <li class="breadcrumb-item active">{{ vehicle.name }}</li>
  </ol>
</div>
```

**Двоколонковий layout:** `col-lg-4` + `col-lg-8`

**Ліва колонка — три картки:**

1. **Інформація** (`card card-outline card-info`):
   - `<dl class="row">` з dt/dd для VPN IP, порт, остання активність, sync статус

2. **Тривоги** (`card card-outline card-warning`):
   - Заголовок + кнопка "Оновити" (hx-get)
   - `<div id="alarms-list">` → include partials/alarms.html

3. **Live** (`card card-outline card-success`):
   - Кнопка `btn btn-success w-100` "▶ Запустити Live"
   - `id="live-btn"`, `onclick="toggleLive('{{ vehicle.id }}')"

**Права колонка:**

```html
<div class="card card-outline card-primary">
  <div class="card-header"><h5>Дані в реальному часі</h5></div>
  <div class="card-body">
    <div id="live-offline" class="text-center py-5 text-muted">
      <i class="bi bi-broadcast fs-1"></i>
      <p>Натисніть «Запустити Live»</p>
    </div>
    <div id="live-data" style="display:none">
      <div id="live-channels" class="row g-2"></div>
      <small class="text-muted float-end mt-2" id="live-updated"></small>
    </div>
    <div id="live-vehicle-offline" style="display:none" class="text-center py-5">
      <i class="bi bi-wifi-off fs-1 text-danger"></i>
      <p class="text-danger">Авто недоступне</p>
    </div>
  </div>
</div>
```

**Live JS блок** — зберегти логіку без змін. Оновити лише CSS класи:
- Кнопка "Запустити": `btn btn-success w-100`
- Кнопка "Зупинити": `btn btn-danger w-100`
- Картка каналу в live-channels:
```javascript
div.className = 'col-6 col-md-4';
div.innerHTML = `
  <div class="info-box">
    <div class="info-box-content">
      <span class="info-box-text">${ch.channel_id ?? ''}</span>
      <span class="info-box-number">${ch.value ?? '—'} ${ch.unit ?? ''}</span>
    </div>
  </div>`;
```

---

## Крок 7 — Оновити `partials/alarms.html`

```html
{% if not alarms %}
<p class="text-muted text-center py-3 mb-0">Активних тривог немає</p>
{% else %}
<div class="list-group list-group-flush">
  {% for a in alarms %}
  <div class="list-group-item list-group-item-action p-2
    {% if a.severity == 'critical' %}list-group-item-danger
    {% elif a.severity == 'warning' %}list-group-item-warning
    {% else %}list-group-item-light{% endif %}">
    <div class="d-flex gap-2 align-items-start">
      <span>
        {% if a.severity == 'critical' %}🔴
        {% elif a.severity == 'warning' %}🟡
        {% else %}⚪{% endif %}
      </span>
      <div>
        <p class="mb-0 small fw-medium">{{ a.message }}</p>
        <small class="text-muted">{{ a.triggered_at.strftime('%d.%m %H:%M') }}</small>
      </div>
    </div>
  </div>
  {% endfor %}
</div>
{% endif %}
```

---

## Крок 8 — Оновити `admin.html`

**Tabs → AdminLTE nav-pills:**
```html
<ul class="nav nav-pills mb-3">
  <li class="nav-item">
    <a class="nav-link {% if tab == 'users' %}active{% endif %}"
       href="/admin?tab=users">
      Користувачі
      {% set pending_count = users | selectattr('status', 'equalto', 'pending') | list | length %}
      {% if pending_count > 0 %}
      <span class="badge bg-danger ms-1">{{ pending_count }}</span>
      {% endif %}
    </a>
  </li>
  <li class="nav-item">
    <a class="nav-link {% if tab == 'vehicles' %}active{% endif %}"
       href="/admin?tab=vehicles">Авто</a>
  </li>
</ul>
```

**Таблиця Users** → Bootstrap table:
```html
<div class="card">
  <div class="card-body p-0">
    <table class="table table-hover mb-0">
      <thead class="table-light">
        <tr>
          <th>Email / Ім'я</th>
          <th>Роль</th>
          <th>Статус</th>
          <th>Зареєстровано</th>
          <th></th>
        </tr>
      </thead>
      <tbody id="users-table">
        {% for u in users %}{% include "partials/user_row.html" %}{% endfor %}
      </tbody>
    </table>
  </div>
</div>
```

**Таблиця Vehicles + форма додавання** — аналогічно Bootstrap table + `card` з `card-body` для форми.

---

## Крок 9 — Оновити `partials/user_row.html`

**Бейджі ролей і статусів:**
```html
<!-- role -->
{% if u.role == 'superuser' %}
<span class="badge bg-danger">superuser</span>
{% else %}
<span class="badge bg-secondary">owner</span>
{% endif %}

<!-- status -->
{% if u.status == 'active' %}
<span class="badge bg-success">active</span>
{% elif u.status == 'pending' %}
<span class="badge bg-warning text-dark">pending</span>
{% elif u.status == 'blocked' %}
<span class="badge bg-danger">blocked</span>
{% endif %}
```

**Кнопки дій** — AdminLTE/Bootstrap:
```html
<!-- pending -->
<button class="btn btn-success btn-sm" hx-post="..." hx-target="..." hx-swap="...">Підтвердити</button>
<button class="btn btn-secondary btn-sm" hx-post="..." ...>Відхилити</button>

<!-- active -->
<button class="btn btn-outline-danger btn-sm" hx-post="..." hx-confirm="..." ...>Блокувати</button>

<!-- blocked -->
<button class="btn btn-outline-success btn-sm" hx-post="..." ...>Розблокувати</button>
```

HTMX атрибути (`hx-post`, `hx-target`, `hx-swap`) — зберегти без змін.

---

## Крок 10 — Очистити Tailwind

1. Видалити зі всіх шаблонів `<script src="https://cdn.tailwindcss.com"></script>`
2. Видалити зі всіх шаблонів блок `tailwind.config`
3. Перевірити що жодного `class="..."` не містить Tailwind-утиліт (bg-gray-*, text-sm, rounded-xl, тощо)

---

## Перевірка після міграції

```bash
# Запустити сервер
docker compose up api -d

# Перевірити сторінки:
# /login         — сторінка входу (AdminLTE login-box)
# /fleet         — картки авто з HTMX оновленням кожні 30 сек
# /vehicles/{id} — деталі авто + Live WebSocket
# /admin         — таблиці з HTMX кнопками

# Перевірити що HTMX партіали працюють:
# - кнопки approve/block/unblock в /admin
# - кнопка "Оновити" в alarms
# - автооновлення fleet-grid

# Перевірити WebSocket live:
# - натиснути "Запустити Live" на сторінці авто
# - ws:// або wss:// з'єднання у DevTools → Network
```

---

## Можливі проблеми

**AdminLTE sidebar не відкривається:**
Переконатись що `adminlte.min.js` підключено після Bootstrap JS і DOM завантажено.

**HTMX конфліктує з Bootstrap:**
HTMX не залежить від CSS-фреймворку — конфліктів не буде. Якщо є проблеми з `hx-swap="outerHTML"` і Bootstrap-компонентами — додати `hx-on::after-settle="..." ` для реініціалізації якщо потрібно.

**Bootstrap і AdminLTE версії:**
AdminLTE v4 вимагає Bootstrap 5.3+. Не підключати Bootstrap окремо — він вже включений в `adminlte.min.css` / `adminlte.min.js`.

**CDN замість локальних файлів:**
Якщо локальне встановлення ускладнене, можна тимчасово використати CDN:
```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/admin-lte@4/dist/css/adminlte.min.css">
<script src="https://cdn.jsdelivr.net/npm/admin-lte@4/dist/js/adminlte.min.js"></script>
```
