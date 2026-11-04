# Onigiri — Production Deployment Guide

Руководство по развёртыванию приложения **Onigiri** (React Telegram Mini App + FastAPI Backend) на сервере Ubuntu с использованием Docker Compose и Nginx Proxy Manager (NPM).

---

## Архитектура развёртывания

- **onigiri-frontend**: Nginx (Alpine), раздаёт статический бандл SPA. Порт `80` (только внутри Docker-сети).
- **onigiri-backend**: Uvicorn + FastAPI (Python 3.12). Порт `8000` (только внутри Docker-сети).
- **База данных**: SQLite с постоянным томом `onigiri_db_data` (путь `/app/data/onigiri.db`).
- **Сеть**: Внешняя сеть `vaultwarden_proxy`, объединяющая сервисы с Nginx Proxy Manager.
- **Домены**:
  - Фронтенд: `https://onigiri.punk.uz`
  - Бэкенд API: `https://api-onigiri.punk.uz`
- **Каталог установки на сервере**: `/opt/onigiri`

---

## 1. Установка Docker и Docker Compose (при необходимости)

Если Docker ещё не установлен на сервере Ubuntu:

```bash
# Обновление пакетов и установка зависимостей
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# Добавление официального GPG ключа Docker
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Добавление репозитория Docker
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Установка Docker Engine и Compose Plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Проверка версий
docker --version
docker compose version
```

---

## 2. Настройка SSH Deploy Key для приватного репозитория

Так как репозиторий `admpunkzic-bit/Onigiri` является приватным, для безопасного доступа с сервера без ввода паролей и личных токенов используется **SSH Deploy Key** с правами **только на чтение (read-only)**.

### Шаг 2.1. Генерация ключа на сервере Ubuntu

Выполните на сервере от имени вашего пользователя (или root):

```bash
# Создание директории .ssh, если отсутствует
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# Генерация специализированного ключа типа Ed25519
ssh-keygen -t ed25519 -C "deploy_onigiri_server" -f ~/.ssh/id_ed25519_onigiri -N ""

# Настройка прав доступа к приватному ключу
chmod 600 ~/.ssh/id_ed25519_onigiri
chmod 644 ~/.ssh/id_ed25519_onigiri.pub
```

### Шаг 2.2. Добавление публичного ключа в GitHub

1. Выведите публичный ключ на экран сервера:
   ```bash
   cat ~/.ssh/id_ed25519_onigiri.pub
   ```
2. Скопируйте строку (начинается с `ssh-ed25519 ...`).
3. Откройте в браузере репозиторий: **https://github.com/admpunkzic-bit/Onigiri/settings/keys**
4. Нажмите кнопку **«Add deploy key»**:
   - **Title**: `Ubuntu Server Production (Read-Only)`
   - **Key**: вставьте скопированный публичный ключ.
   - **Allow write access**: **НЕ ОТМЕЧАТЬ** (оставить выключенным — ключ должен быть строго read-only!).
5. Нажмите **«Add key»**.

### Шаг 2.3. Настройка SSH Config и проверка связи

Создайте или дополните файл `~/.ssh/config`:

```bash
cat << 'EOF' >> ~/.ssh/config

Host github-onigiri
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_onigiri
    IdentitiesOnly yes
EOF

chmod 600 ~/.ssh/config

# Проверка соединения с GitHub
ssh -i ~/.ssh/id_ed25519_onigiri -T git@github.com
# Должен вернуть: "Hi admpunkzic-bit/Onigiri! You've successfully authenticated..."
```

---

## 3. Клонирование репозитория в `/opt/onigiri`

Клонирование выполняется по SSH URL:

```bash
# Создание каталога /opt/onigiri
sudo mkdir -p /opt/onigiri
sudo chown $USER:$USER /opt/onigiri

# Клонирование репозитория
git clone git@github.com:admpunkzic-bit/Onigiri.git /opt/onigiri

# Переход в проект
cd /opt/onigiri
```

---

## 4. Подготовка переменных окружения (.env)

Переменные окружения не хранятся в Git. Создайте файлы из безопасных шаблонов:

```bash
cd /opt/onigiri

# Шаблон для фронтенда:
cp frontend/.env.example frontend/.env

# Шаблон для бэкенда:
cp backend/.env.example backend/.env
```

Файл `backend/.env` (при необходимости тонкой настройки):
```env
CORS_ORIGINS=https://onigiri.punk.uz
SQLITE_DB_PATH=/app/data/onigiri.db
```

---

## 5. Проверка внешней Docker-сети `vaultwarden_proxy`

Контейнеры Onigiri должны подключаться к той же сети, в которой работает Nginx Proxy Manager (NPM).

> [!IMPORTANT]
> **Не создавайте новую сеть вслепую!**
> Если сеть `vaultwarden_proxy` отсутствует, сначала проверьте состояние NPM: убедитесь, что стек NPM запущен и в какую сеть он фактически включён.

Проверка сети и подключённого в неё контейнера NPM:
```bash
docker network inspect vaultwarden_proxy
```

В выводе команды (в секции `Containers`) должен присутствовать контейнер Nginx Proxy Manager (например, `nginx-proxy-manager` или `npm`).

---

## 6. Сборка и запуск контейнеров

```bash
cd /opt/onigiri

# Сборка образов и запуск в фоне
docker compose up -d --build

# Проверка статуса сервисов
docker compose ps
```

Оба сервиса должны быть в статусе `Up`, а для `onigiri-backend` должен отображаться статус `(healthy)`:
```text
NAME               IMAGE               COMMAND                  SERVICE    STATUS                    PORTS
onigiri-backend    onigiri-backend     "uvicorn main:app --…"   backend    Up ... (healthy)          8000/tcp
onigiri-frontend   onigiri-frontend    "nginx -g 'daemon of…"   frontend   Up ...                    80/tcp
```

> [!WARNING]
> Порты 80 и 8000 **не публикуются на хост** — доступ к сервисам происходит исключительно внутри сети `vaultwarden_proxy` через NPM.

---

## 7. Настройка Nginx Proxy Manager (NPM)

В веб-интерфейсе NPM добавьте два Proxy Host:

### 1. Хост Frontend (Telegram Mini App)
- **Domain Names**: `onigiri.punk.uz`
- **Scheme**: `http`
- **Forward Hostname / IP**: `onigiri-frontend`
- **Forward Port**: `80`
- **Block Common Exploits**: ON
- **Websockets Support**: ON
- **SSL**:
  - SSL Certificate: выберите/выпустите Let's Encrypt для `onigiri.punk.uz`
  - Force SSL: ON
  - HTTP/2 Support: ON
  - HSTS Enabled: ON

### 2. Хост Backend (API)
- **Domain Names**: `api-onigiri.punk.uz`
- **Scheme**: `http`
- **Forward Hostname / IP**: `onigiri-backend`
- **Forward Port**: `8000`
- **Block Common Exploits**: ON
- **SSL**:
  - SSL Certificate: выберите/выпустите Let's Encrypt для `api-onigiri.punk.uz`
  - Force SSL: ON
  - HTTP/2 Support: ON
  - HSTS Enabled: ON

---

## 8. Проверка работоспособности

### 8.1. Проверка API Health Endpoint снаружи:
```bash
curl -i https://api-onigiri.punk.uz/api/health
```
Ожидаемый ответ: `HTTP/2 200` с JSON:
```json
{
  "status": "ok",
  "service": "onigiri-api",
  "version": "0.1.0",
  "timestamp": "..."
}
```

### 8.2. Проверка Frontend:
Откройте в браузере `https://onigiri.punk.uz`:
- Страница открывается без ошибок.
- Индикатор сервера в шапке показывает статус **«Подключено»**.
- Все маршруты (`/search`, `/library`, `/history`, `/settings`) переключаются без перезагрузки страницы.

---

## 9. Обновление проекта (Deploy updates)

Для обновления работающего приложения из Git:

```bash
cd /opt/onigiri
git pull origin main
docker compose up -d --build
```

---

## 10. Резервное копирование и сохранение SQLite

База данных хранится в именованном Docker volume `onigiri_db_data` (внутри контейнера: `/app/data/onigiri.db`).

> [!CAUTION]
> **Никогда не используйте команду `docker compose down -v`!**
> Флаг `-v` удаляет именованные volumes, что приведёт к безвозвратной потере базы данных SQLite.
> Для плановой остановки сервисов используйте строго:
> `docker compose down` (без флага `-v`).

### 10.1. Создание резервной копии:
```bash
# Создание консистентного snapshot SQLite через API Python/sqlite3:
docker exec onigiri-backend python -c "
import sqlite3
src = sqlite3.connect('/app/data/onigiri.db')
bck = sqlite3.connect('/app/data/backup.db')
src.backup(bck)
bck.close()
src.close()
"

# Копирование резервной копии из контейнера на хост:
mkdir -p /opt/backups/onigiri
docker cp onigiri-backend:/app/data/backup.db /opt/backups/onigiri/onigiri_$(date +%Y%m%d_%H%M%S).db
docker exec onigiri-backend rm /app/data/backup.db
```

### 10.2. Восстановление из резервной копии:
```bash
cd /opt/onigiri
docker compose stop backend
sudo cp /opt/backups/onigiri/onigiri_YYYYMMDD_HHMMSS.db /var/lib/docker/volumes/onigiri_db_data/_data/onigiri.db
docker compose start backend
```
