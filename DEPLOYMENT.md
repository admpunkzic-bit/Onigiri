# Onigiri — Production Deployment Guide

Руководство по развёртыванию приложения **Onigiri** (React Telegram Mini App + FastAPI Backend) на сервере Ubuntu с использованием Docker Compose и Nginx Proxy Manager.

---

## Архитектура развёртывания

- **onigiri-frontend**: Nginx 1.27 (Alpine), раздаёт статический бандл SPA. Порт `80` (только внутри Docker-сети).
- **onigiri-backend**: Uvicorn + FastAPI (Python 3.12). Порт `8000` (только внутри Docker-сети).
- **База данных**: SQLite c постоянным томом `onigiri_db_data`.
- **Сеть**: Внешняя сеть `vaultwarden_proxy`, объединяющая сервисы с Nginx Proxy Manager (NPM).
- **Домены**:
  - Фронтенд: `https://onigiri.punk.uz`
  - Бэкенд API: `https://api-onigiri.punk.uz`

---

## 1. Установка Docker и Docker Compose

Если Docker ещё не установлен на сервере Ubuntu:

```bash
# Обновление пакетов и установка необходимых утилит
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# Добавление официального GPG ключа Docker
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Добавление репозитория
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Установка Docker Engine и Compose Plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Проверка
docker --version
docker compose version
```

---

## 2. Клонирование репозитория

```bash
# Переход в рабочую директорию (например, /opt или домашний каталог)
cd /opt
sudo git clone https://github.com/admpunkzic-bit/Onigiri.git
cd Onigiri
```

---

## 3. Подготовка переменных окружения (.env)

Файлы `.env` не хранятся в репозитории. Создайте их на основе шаблонов:

```bash
# Для фронтенда (если требуется переопределить API URL при сборке):
cp frontend/.env.example frontend/.env

# Для бэкенда:
cp backend/.env.example backend/.env
```

Содержимое `backend/.env` (при необходимости):
```env
CORS_ORIGINS=https://onigiri.punk.uz
SQLITE_DB_PATH=/app/data/onigiri.db
```

---

## 4. Создание каталога данных и томов

Docker Compose автоматически создаст именованный volume `onigiri_db_data`. При необходимости создания локального каталога вручную:

```bash
sudo mkdir -p /var/lib/docker/volumes/onigiri_db_data/_data
```

---

## 5. Проверка внешней Docker-сети

Контейнеры Onigiri подключаются к существующей сети `vaultwarden_proxy`. Убедитесь, что сеть создана:

```bash
docker network ls | grep vaultwarden_proxy
```

Если сеть ещё не создана:
```bash
docker network create vaultwarden_proxy
```

---

## 6. Сборка и запуск контейнеров

```bash
# Сборка образов и запуск в фоновом режиме
docker compose up -d --build

# Проверка статуса запущенных контейнеров
docker compose ps

# Просмотр логов
docker compose logs -f
```

---

## 7. Настройка Nginx Proxy Manager (NPM)

Поскольку контейнеры подключены к сети `vaultwarden_proxy`, Nginx Proxy Manager может напрямую проксировать запросы по именам контейнеров:

### Хост 1: Frontend (Telegram Mini App)
- **Domain Names**: `onigiri.punk.uz`
- **Scheme**: `http`
- **Forward Hostname / IP**: `onigiri-frontend`
- **Forward Port**: `80`
- **Block Common Exploits**: Включено (ON)
- **Websockets Support**: Включено (ON)
- **SSL**:
  - Выберите сертификат Let's Encrypt для `onigiri.punk.uz`
  - Force SSL: Включено (ON)
  - HTTP/2 Support: Включено (ON)
  - HSTS Enabled: Включено (ON)

### Хост 2: Backend API
- **Domain Names**: `api-onigiri.punk.uz`
- **Scheme**: `http`
- **Forward Hostname / IP**: `onigiri-backend`
- **Forward Port**: `8000`
- **Block Common Exploits**: Включено (ON)
- **SSL**:
  - Выберите сертификат Let's Encrypt для `api-onigiri.punk.uz`
  - Force SSL: Включено (ON)
  - HTTP/2 Support: Включено (ON)
  - HSTS Enabled: Включено (ON)

---

## 8. Проверка работоспособности (Healthcheck)

После настройки NPM проверьте доступность эндпоинта здоровья:

```bash
curl -I https://api-onigiri.punk.uz/api/health
```

Ожидаемый ответ:
```json
{
  "status": "ok",
  "service": "onigiri-api",
  "version": "0.1.0",
  "timestamp": "2026-11-05T..."
}
```

Также состояние контейнера бэкенда отображается в `docker compose ps` со статусом `healthy`:
```bash
docker compose ps
# onigiri-backend   ...   Up ... (healthy)   8000/tcp
```

---

## 9. Обновление проекта (CI/CD / Manual Deployment)

Для обновления работающего приложения до последней версии из ветки `main`:

```bash
cd /opt/Onigiri
git pull origin main
docker compose up -d --build
```

Благодаря multi-stage кэшированию Docker и раздельному хранению базы данных, обновление проходит без потери данных SQLite и с минимальным временем простоя.

---

## 10. Резервное копирование SQLite

База данных сохраняется в volume `onigiri_db_data`.

### Создание резервной копии:
```bash
# Безопасный бэкап SQLite с использованием команды .backup или утилиты sqlite3
docker exec onigiri-backend python -c "
import sqlite3
src = sqlite3.connect('/app/data/onigiri.db')
bck = sqlite3.connect('/app/data/backup_$(date +%Y%m%d_%H%M%S).db')
src.backup(bck)
bck.close()
src.close()
print('Backup created successfully')
"

# Либо копирование файла с хоста
sudo cp /var/lib/docker/volumes/onigiri_db_data/_data/onigiri.db /backup/onigiri_$(date +%Y%m%d_%H%M%S).db
```

### Восстановление из копии:
```bash
docker compose stop backend
sudo cp /backup/onigiri_YYYYMMDD_HHMMSS.db /var/lib/docker/volumes/onigiri_db_data/_data/onigiri.db
docker compose start backend
```
