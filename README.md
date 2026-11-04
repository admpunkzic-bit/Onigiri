# 🍙 Onigiri

Манга-читалка в формате Telegram Mini App.

## О проекте

Onigiri — удобное приложение для поиска, просмотра и чтения манги на смартфоне. Проект построен как Telegram Mini App с React-фронтендом и FastAPI-бэкендом.

## Структура проекта

```
Onigiri/
├── frontend/               # React + TypeScript + Vite
│   └── src/
│       ├── components/     # UI-компоненты
│       ├── pages/          # Страницы приложения
│       ├── layouts/        # Макеты (layouts)
│       ├── hooks/          # Кастомные React-хуки
│       ├── services/       # API-сервисы
│       ├── store/          # Управление состоянием
│       └── styles/         # Стили
├── backend/                # Python + FastAPI
│   ├── api/                # Роуты API
│   ├── models/             # Модели данных
│   ├── schemas/            # Pydantic-схемы
│   ├── services/           # Бизнес-логика
│   ├── database/           # Подключение к БД (SQLite)
│   └── tests/              # Тесты
├── docs/                   # Документация
├── README.md
└── .gitignore
```

## Технологии

| Слой | Стек |
|------|------|
| Frontend | React, TypeScript, Vite, Tailwind CSS, Lucide React |
| Backend | Python, FastAPI, SQLite |

## Установка и запуск

### Требования

- Node.js 20+
- Python 3.12+
- Git

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Фронтенд будет доступен по адресу: http://localhost:5173

### Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Бэкенд будет доступен по адресу: http://localhost:8000

### Проверка работы API

```bash
curl http://localhost:8000/api/health
```

Ожидаемый ответ:
```json
{
  "status": "ok",
  "service": "onigiri-api",
  "version": "0.1.0",
  "timestamp": "2026-01-01T00:00:00+00:00"
}
```

## Тесты

### Backend

```bash
cd backend
python -m pytest tests/ -v
```

### Frontend

```bash
cd frontend
npm run build     # Проверка сборки
npx tsc --noEmit  # Проверка типов TypeScript
```

## Цветовая палитра

| Токен | Цвет | HEX |
|-------|------|-----|
| Background | 🟣 | `#101116` |
| Surface | 🟣 | `#191B24` |
| Accent | 🟣 | `#9B6DFF` |
| Secondary accent | 🔵 | `#6D8CFF` |
| Primary text | ⚪ | `#F5F5F7` |
| Secondary text | 🔘 | `#9295A3` |

## Лицензия

Внутренний проект.
