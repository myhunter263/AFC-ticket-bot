# Production Deploy Guide — Ubuntu VPS
# Репозиторий: https://github.com/myhunter263/AFC-ticket-bot
# Папка с проектом внутри репо: discord-ticket-bot/

---

## 1. Подключение к VPS

```bash
ssh root@YOUR_VPS_IP
```

> Замените `YOUR_VPS_IP` на реальный IP-адрес вашего VPS.

---

## 2. Обновление системы и установка Docker

```bash
apt-get update && apt-get upgrade -y

# Установка зависимостей
apt-get install -y curl git ufw

# Установка Docker одной командой
curl -fsSL https://get.docker.com | sh

# Установка Docker Compose Plugin
apt-get install -y docker-compose-plugin

# Проверка установки
docker --version
docker compose version
```

---

## 3. Настройка Firewall

```bash
ufw default deny incoming
ufw default allow outgoing

ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS

ufw --force enable
ufw status
```

---

## 4. Клонирование репозитория и переход в папку проекта

```bash
cd /opt

# Клонируем весь репозиторий AFC-ticket-bot
git clone https://github.com/myhunter263/AFC-ticket-bot.git

# Переходим в папку проекта внутри репозитория
cd /opt/AFC-ticket-bot/discord-ticket-bot
```

> Рабочая директория бота: `/opt/AFC-ticket-bot/discord-ticket-bot`
> Все последующие команды выполняются именно из этой папки.

---

## 5. Настройка .env

```bash
# Находимся в /opt/AFC-ticket-bot/discord-ticket-bot
cp .env.example .env
nano .env
```

Заполнить обязательные переменные:

```env
DISCORD_TOKEN=ваш_токен_бота
DISCORD_GUILD_ID=ваш_id_сервера
POSTGRES_PASSWORD=придумайте_сложный_пароль
POSTGRES_USER=ticketbot
POSTGRES_DB=ticketbot
POSTGRES_HOST=db
```

> `DISCORD_GUILD_ID` — ID вашего Discord-сервера (для быстрой синхронизации команд).
> Если оставить пустым — команды зарегистрируются глобально (до 1 часа задержки).

Ограничить права на файл:

```bash
chmod 600 .env
```

---

## 6. Первый запуск

```bash
# Находимся в /opt/AFC-ticket-bot/discord-ticket-bot

# Создать папку для логов
mkdir -p logs

# Собрать Docker-образы
docker compose build --no-cache

# Запустить в фоновом режиме
docker compose up -d

# Проверить статус контейнеров (оба должны быть Up)
docker compose ps

# Смотреть логи бота в реальном времени
docker compose logs -f bot
```

Ожидаемый вывод в логах:
```
[INFO] Database initialized successfully.
[INFO] Loaded cog: cogs.setup
[INFO] Loaded cog: cogs.admin
[INFO] Loaded cog: cogs.tickets
[INFO] Synced N commands to guild ...
[INFO] Bot is ready! Logged in as ...
```

---

## 7. Первоначальная настройка бота в Discord

После того как бот онлайн:

1. Введите `/setup` на вашем сервере — синхронизирует все slash-команды и создаёт статусы по умолчанию
2. Введите `/admin` — откроет главную панель управления
3. В панели: **Формы** → создайте форму с нужными полями
4. В панели: **Панели тикетов** → **Создать панель** → выберите канал и форму → **Опубликовать**

---

## 8. Просмотр логов

```bash
cd /opt/AFC-ticket-bot/discord-ticket-bot

# Логи бота
docker compose logs -f bot

# Логи базы данных
docker compose logs -f db

# Последние 100 строк без следования
docker compose logs --tail=100 bot
```

---

## 9. Обновление проекта без потери данных

```bash
# Перейти в корень репозитория
cd /opt/AFC-ticket-bot

# Получить последние изменения с GitHub
git pull origin main

# Перейти в папку проекта
cd discord-ticket-bot

# Пересобрать только образ бота (БД не останавливается и не трогается)
docker compose build bot

# Перезапустить только контейнер бота
docker compose up -d --no-deps bot

# Убедиться, что всё запустилось
docker compose ps
docker compose logs --tail=30 bot
```

> **Важно:** `docker compose up -d --no-deps bot` перезапускает только бота.
> PostgreSQL и все данные остаются нетронутыми.

---

## 10. Резервное копирование PostgreSQL

### Ручной дамп (выполнять из `/opt/AFC-ticket-bot/discord-ticket-bot`)

```bash
cd /opt/AFC-ticket-bot/discord-ticket-bot

docker compose exec -T db pg_dump -U ticketbot ticketbot \
  > /opt/backups/db_$(date +%Y%m%d_%H%M%S).sql

echo "Бэкап создан: /opt/backups/db_$(date +%Y%m%d).sql"
```

### Автоматический бэкап через cron (ежедневно в 03:00)

```bash
mkdir -p /opt/backups
crontab -e
```

Добавить строку:

```cron
0 3 * * * cd /opt/AFC-ticket-bot/discord-ticket-bot && docker compose exec -T db pg_dump -U ticketbot ticketbot > /opt/backups/db_$(date +\%Y\%m\%d).sql 2>&1
```

Проверить, что cron работает:

```bash
crontab -l
ls -lh /opt/backups/
```

### Восстановление из дампа

```bash
cd /opt/AFC-ticket-bot/discord-ticket-bot

docker compose exec -T db psql -U ticketbot ticketbot < /opt/backups/db_20240101.sql
```

---

## 11. Автозапуск при перезагрузке VPS

Контейнеры автоматически стартуют при перезагрузке сервера (политика `restart: unless-stopped` в compose).

Убедиться, что Docker включён в автозапуск:

```bash
systemctl enable docker
systemctl is-enabled docker
```

Проверить после перезагрузки:

```bash
reboot
# после перезагрузки:
ssh root@YOUR_VPS_IP
docker ps
```

---

## 12. Автообновление — GitHub Actions (рекомендуется)

Создать файл `.github/workflows/deploy.yml` в репозитории `AFC-ticket-bot`:

```yaml
name: Deploy AFC Ticket Bot

on:
  push:
    branches: [main]
    paths:
      - "discord-ticket-bot/**"

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Deploy to VPS via SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            set -e

            echo "==> Pulling latest changes from GitHub..."
            cd /opt/AFC-ticket-bot
            git pull origin main

            echo "==> Rebuilding bot image..."
            cd discord-ticket-bot
            docker compose build bot

            echo "==> Restarting bot container..."
            docker compose up -d --no-deps bot

            echo "==> Checking status..."
            docker compose ps
            echo "==> Deploy complete!"
```

### Настройка Secrets в GitHub

Перейти: `https://github.com/myhunter263/AFC-ticket-bot` → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret | Значение |
|--------|----------|
| `VPS_HOST` | IP-адрес вашего VPS |
| `VPS_USER` | `root` (или имя пользователя) |
| `VPS_SSH_KEY` | Содержимое файла `~/.ssh/id_rsa` (приватный ключ) |

### Добавить SSH-ключ на VPS

```bash
# На локальной машине (если ключа ещё нет)
ssh-keygen -t ed25519 -C "github-actions-deploy"

# Скопировать публичный ключ на VPS
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@YOUR_VPS_IP

# Скопировать содержимое приватного ключа в GitHub Secret VPS_SSH_KEY
cat ~/.ssh/id_ed25519
```

**Как работает:** При каждом `git push` в ветку `main` (если изменены файлы внутри `discord-ticket-bot/`) GitHub Actions автоматически подключится к VPS, сделает `git pull` и перезапустит бота. БД при этом не трогается.

---

## 13. Мониторинг

```bash
cd /opt/AFC-ticket-bot/discord-ticket-bot

# Статус контейнеров
docker compose ps

# Использование CPU и RAM в реальном времени
docker stats

# Использование дискового пространства
docker system df

# Проверить что бот жив (если нет ошибок — всё хорошо)
docker compose logs --tail=20 bot | grep -E "ERROR|WARNING|ready"
```

---

## 14. Рекомендации по безопасности

```bash
# 1. Ограничить права на .env — ОБЯЗАТЕЛЬНО
chmod 600 /opt/AFC-ticket-bot/discord-ticket-bot/.env

# 2. Отключить вход по паролю SSH (использовать только ключи)
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

# 3. Установить Fail2ban против брутфорса SSH
apt-get install -y fail2ban
systemctl enable --now fail2ban

# 4. Регулярно обновлять базовые образы Docker
docker compose pull db
docker compose up -d db

# 5. Никогда не коммитить .env в репозиторий
# .gitignore уже содержит строку ".env"

# 6. Ротация логов уже настроена в docker-compose.yml (max-size: 10m, max-file: 3)
```

---

## 15. Полный Quick Start (все команды подряд)

```bash
# --- На VPS ---
ssh root@YOUR_VPS_IP

apt-get update && apt-get upgrade -y
apt-get install -y curl git ufw
curl -fsSL https://get.docker.com | sh
apt-get install -y docker-compose-plugin

ufw allow 22 && ufw allow 80 && ufw allow 443
ufw --force enable

cd /opt
git clone https://github.com/myhunter263/AFC-ticket-bot.git
cd /opt/AFC-ticket-bot/discord-ticket-bot

cp .env.example .env
nano .env           # <-- вписать DISCORD_TOKEN и POSTGRES_PASSWORD

chmod 600 .env
mkdir -p logs /opt/backups

docker compose build --no-cache
docker compose up -d
docker compose logs -f bot
```

---

## Шпаргалка — частые команды

| Действие | Команда |
|----------|---------|
| Запустить | `docker compose up -d` |
| Остановить | `docker compose down` |
| Перезапустить бота | `docker compose restart bot` |
| Логи бота | `docker compose logs -f bot` |
| Обновить из GitHub | `cd /opt/AFC-ticket-bot && git pull && cd discord-ticket-bot && docker compose build bot && docker compose up -d --no-deps bot` |
| Сделать бэкап БД | `docker compose exec -T db pg_dump -U ticketbot ticketbot > /opt/backups/db_$(date +%Y%m%d).sql` |
| Войти в PostgreSQL | `docker compose exec db psql -U ticketbot ticketbot` |
| Статус контейнеров | `docker compose ps` |

> Все команды выполняются из директории `/opt/AFC-ticket-bot/discord-ticket-bot`
