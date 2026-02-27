# AutoZabbix — Zabbix для мониторинга сервера Visiology

Развёртывание **Zabbix 7.4** в Docker для мониторинга сервера с платформой Visiology: хост, Docker/Swarm, сеть, диск, триггер при нехватке свободного места. Поддержка доступа по **http://IP:8080** или по **http://IP/v3/zabbix** через reverse proxy Visiology.

---

## Содержание

- [Установка на сервере](#установка-на-сервере)
- [Возможности](#возможности)
- [Требования](#требования)
- [Дашборд «Главный экран»](#дашборд-главный-экран)
- [Быстрый старт (установщик)](#быстрый-старт-установщик)
- [Ручная установка](#ручная-установка)
- [Структура репозитория](#структура-репозитория)
- [Конфигурация](#конфигурация)
- [Доступ и учётные данные](#доступ-и-учётные-данные)
- [Устранение неполадок](#устранение-неполадок)
- [Обновление после git pull](#обновление-после-git-pull)
- [Полезные команды](#полезные-команды)

---

## Установка на сервере

На **сервере с Linux** (где будет работать Zabbix) клонируйте репозиторий и запустите установщик:

```bash
git clone https://github.com/heupoh4ur/visiology_auto_zabbix.git
cd visiology_auto_zabbix
chmod +x install-zabbix.sh
./install-zabbix.sh
```

Установщик задаст вопросы: каталог установки, режим доступа (http://IP:8080 или /v3/zabbix), интеграция с Visiology, настройка через API. После завершения откройте в браузере выданный адрес (логин **Admin**, пароль **zabbix**).

**Режим отладки:** `./install-zabbix.sh -d`

---

## Возможности

- **Zabbix 7.4** в Docker: PostgreSQL 17, Zabbix Server, Zabbix Web (Nginx), Zabbix Agent 2.
- Мониторинг **хоста**: CPU, память, диск, сеть, процессы (шаблон **Linux by Zabbix agent 2**).
- Мониторинг **Docker и Swarm**: контейнеры, образы, состояние Docker Engine (шаблон **Docker by Zabbix agent 2**).
- Триггер **«Свободно места на диске меньше 25%»** (Warning) для корня и при необходимости для других разделов.
- Два режима доступа к веб-интерфейсу:
  - **Стандартный:** `http://IP:8080`.
  - **Через Visiology:** `http://IP/v3/zabbix` (с добавлением блока в reverse proxy платформы).
- **Установщик в один клик** (`install-zabbix.sh`): копирование файлов, запуск контейнеров, настройка через API (хост, шаблоны, триггер), опциональная интеграция с конфигами Visiology.
- **Настройка через API** без ручного ввода в UI: группа хостов, хост с агентом, привязка шаблонов, триггер, дашборд **«Главный экран»** (скрипт `zabbix-init-config.py`). Подробнее — раздел [Дашборд «Главный экран»](#дашборд-главный-экран).

---

## Требования

- **ОС:** Linux (сервер, на котором разворачивается Zabbix).
- **Docker** и **Docker Compose** (Compose V2: команда `docker compose`).
- Свободные порты: **8080** (веб), **10051** (сервер), **10050** (агент).
- Для доступа по `/v3/zabbix`: сервер с установленной платформой **Visiology** и reverse proxy на порту 80.
- Для настройки через API: **Python 3** (только стандартная библиотека), **curl**.

---

## Дашборд «Главный экран»

Дашборд создаётся скриптом `zabbix-init-config.py` (при установке через API или при ручном запуске) и предназначен для обзора состояния сервера на одном экране.

### Как устроен дашборд

- **Верхний ряд (сводка и Docker):**
  - **Проблемы по важности** — количество проблем по уровням (Warning, Average, High, Disaster) по группе хостов Visiology. Позволяет сразу увидеть, есть ли критические срабатывания.
  - **Запущенные контейнеры (docker ps)** — виджет «Значение элемента»: вывод команды `docker ps --format "table ..."` (имя, статус, образ). Аналог `docker service ls` / `docker ps` на хосте.
  - **Exited контейнеры** — тот же тип виджета: список контейнеров в состоянии `exited` (команда `docker ps -a --filter status=exited`). Если список пуст, виджет так и отображает; если есть — видно, какие контейнеры остановились.

- **Средний ряд:**
  - **Проблемы и предупреждения** — таблица текущих проблем (триггеров в состоянии «Problem») по группе Visiology: хост, описание, важность, время. Удобно для быстрого реагирования на ворнинги.

- **Нижний ряд (ресурсы и Swarm):**
  - **Свободно места на диске (%)** — виджет «Счётчик» (Gauge): процент свободного места по элементу `vfs.fs.size[/hostfs,pfree]` (корень хоста, т.к. в контейнере агента корень смонтирован как `/hostfs`). Показывает, не переполнен ли диск.
  - **Состояние Docker Swarm** — виджет «Значение элемента»: результат `docker info --format '{{.Swarm.LocalNodeState}}'` (например `active` или `inactive`). Позволяет убедиться, что нода в Swarm в ожидаемом состоянии.

### Откуда берутся данные

- Данные по **проблемам** — из Zabbix (триггеры по шаблонам и кастомным правилам).
- Данные по **контейнерам, Swarm и диску** — с хоста через Zabbix Agent: скрипт создаёт элементы с ключами `docker.containers.running`, `docker.containers.exited`, `docker.swarm.state` (через UserParameter в `agent2.d/98_docker_commands.conf`) и `vfs.fs.size[/hostfs,pfree]`. Виджеты «Запущенные контейнеры», «Exited контейнеры» и «Состояние Docker Swarm» получают данные по Docker API через **curl** в контейнере агента. **Установщик** при установке копирует `Dockerfile.agent2` в каталог установки и собирает образ `zabbix-agent2-with-curl` (с curl) перед запуском контейнеров — тогда виджеты работают. При ручной установке без сборки в стандартном образе zabbix-agent2 нет curl, виджеты Docker/Swarm будут показывать «No data»; чтобы исправить: `docker build -f Dockerfile.agent2 -t zabbix-agent2-with-curl .` в каталоге установки. Виджет диска (`vfs.fs.size`) не зависит от curl.

### Где смотреть

В веб-интерфейсе: **Monitoring → Dashboards** → выберите **«Главный экран»**.

---

## Быстрый старт (установщик)

1. Клонируйте репозиторий на сервер и перейдите в каталог (см. [Установка на сервере](#установка-на-сервере)).

2. Запустите установщик:

```bash
chmod +x install-zabbix.sh
./install-zabbix.sh
```

3. Ответьте на вопросы:
   - **Каталог установки** (по умолчанию `~/zabbix`).
   - **Режим доступа:** `1` — стандартный (http://IP:8080), `2` — по пути /v3/zabbix (http://IP/v3/zabbix).
   - При выборе /v3/zabbix: **добавить ли Zabbix в конфиг Visiology** (reverse proxy) или оставить внешним компонентом.
   - **Выполнять ли настройку через API** (хост, шаблоны, триггер) — по умолчанию да.

4. После завершения откройте веб-интерфейс по выданному адресу (логин **Admin**, пароль **zabbix**).

### Режим отладки

Чтобы видеть подробный вывод и понять, на каком шаге произошла ошибка:

```bash
./install-zabbix.sh -d
```

Включается пошаговый лог и отключается анимация.

### Неинтерактивный запуск

Для CI или запуска без TTY задайте переменные окружения:

```bash
# Стандартный доступ, с настройкой по API
INSTALL_DIR=~/zabbix URL_MODE=standard DO_API_CONFIG=1 ./install-zabbix.sh

# Доступ по /v3/zabbix + интеграция с Visiology
URL_MODE=v3zabbix VISIOLOGY_INTEGRATE=1 DO_API_CONFIG=1 SERVER_IP=192.168.31.100 ./install-zabbix.sh
```

| Переменная | Описание | Пример |
|------------|----------|--------|
| `INSTALL_DIR` | Каталог установки | `~/zabbix` |
| `URL_MODE` | `standard` или `v3zabbix` | `v3zabbix` |
| `DO_API_CONFIG` | `1` — настройка по API, `0` — не выполнять | `1` |
| `VISIOLOGY_INTEGRATE` | `1` — добавить /v3/zabbix в конфиг Visiology (при `v3zabbix`) | `1` |
| `SERVER_IP` | IP сервера (если не задан — определяется автоматически) | `192.168.31.100` |

---

## Ручная установка

Если установщик не используется:

1. Клонируйте репозиторий. В корне клонированного каталога лежат все нужные файлы.
2. Скопируйте в каталог установки (например `~/zabbix`): `docker-compose.yml`, `.env.example` → `.env`, а также `nginx_http_d.conf` (для /v3/zabbix) или `nginx_http_d_standard.conf` → сохранить как `nginx_http_d.conf` (для http://IP:8080). Для виджетов дашборда (контейнеры, Swarm) — каталог `agent2.d` и `Dockerfile.agent2`.
3. Отредактируйте `.env`: пароли, `ZBX_HOSTNAME`, `TZ`. Для доступа по /v3/zabbix добавьте `ZBX_FRONTEND_URL=http://<IP>/v3/zabbix`.
4. Соберите образ агента с curl (в каталоге установки): `docker build -f Dockerfile.agent2 -t zabbix-agent2-with-curl .` (если пропустить — в `.env` укажите `ZABBIX_AGENT2_IMAGE=zabbix/zabbix-agent2:alpine-7.4-latest`).
5. Запустите: `cd ~/zabbix && docker compose up -d`.
6. Настройку хоста, шаблонов и триггера выполните вручную в веб-интерфейсе или через скрипт `zabbix-init-config.py` (см. раздел [Конфигурация](#конфигурация)).

Подробная пошаговая инструкция — в файле **`zabbix_visiology_install.md`**.

---

## Структура репозитория

Все файлы лежат в **корне репозитория** (после клонирования — в каталоге `visiology_auto_zabbix` или как вы назвали при clone):

```
visiology_auto_zabbix/
├── README.md                      # Этот файл
├── zabbix_visiology_install.md   # Подробная инструкция по установке и настройке
├── .gitignore
├── install-zabbix.sh             # Установщик «в один клик»
├── docker-compose.yml            # Сервисы: PostgreSQL, Zabbix Server/Web/Agent 2
├── .env.example                  # Пример переменных окружения для контейнеров
├── nginx_http_d.conf             # Nginx для доступа по /v3/zabbix
├── nginx_http_d_standard.conf    # Nginx для доступа по http://IP:8080
├── Dockerfile.agent2              # Образ агента с curl (виджеты Docker/Swarm); установщик собирает его
├── agent2.d/
│   ├── 98_docker_commands.conf   # UserParameter для docker.containers.* и docker.swarm.state
│   └── 99_server_active.conf     # Переопределение ServerActive для агента
├── zabbix-init-config.py         # Настройка Zabbix через API (хост, шаблоны, триггер, дашборд)
└── zabbix-init-config.env        # Пример переменных для zabbix-init-config.py
```

**Минимальный набор для установщика:**  
`install-zabbix.sh`, `docker-compose.yml`, `.env.example`, `nginx_http_d.conf`, `nginx_http_d_standard.conf`.  
Для настройки через API — `zabbix-init-config.py`, `zabbix-init-config.env`. Для агента и виджетов дашборда — каталог `agent2.d` (оба конфига) и `Dockerfile.agent2` (установщик копирует его и собирает образ перед запуском контейнеров).

---

## Конфигурация

### Переменные окружения контейнеров (`.env`)

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | База данных | `zabbix` |
| `ZABBIX_WEB_PORT`, `ZABBIX_SERVER_PORT` | Порты веб и сервера | `8080`, `10051` |
| `ZABBIX_AGENT2_IMAGE` | Образ агента (установщик собирает `zabbix-agent2-with-curl`) | `zabbix-agent2-with-curl` |
| `ZBX_HOSTNAME` | Имя хоста в Zabbix | `Visiology-Server` |
| `ZBX_FRONTEND_URL` | URL веб-интерфейса (для редиректов) | при /v3/zabbix: `http://IP/v3/zabbix` |
| `TZ` | Часовой пояс | `Europe/Moscow` |

### Настройка через API (без установщика)

Скрипт `zabbix-init-config.py` создаёт группу хостов, хост с интерфейсом агента, подключает шаблоны **Linux by Zabbix agent 2** и **Docker by Zabbix agent 2**, добавляет триггер «свободно места на диске меньше 25%» и дашборд **«Главный экран»** с виджетами для отображения всех проблем и предупреждений на одном экране.

1. Скопируйте `zabbix-init-config.py` и при необходимости `zabbix-init-config.env` в каталог установки или туда, откуда будете запускать.
2. Задайте переменные (файл `zabbix-init-config.local.env` или экспорт в shell):
   - `ZABBIX_URL` — URL веб-интерфейса (например `http://192.168.31.100:8080`);
   - `ZABBIX_USER`, `ZABBIX_PASSWORD` — логин и пароль (по умолчанию Admin / zabbix);
   - `ZBX_HOSTNAME` — имя хоста (должно совпадать с `ZBX_HOSTNAME` в `.env` агента);
   - `ZABBIX_AGENT_IP` — IP, по которому сервер подключается к агенту.
3. Запустите: `python3 zabbix-init-config.py`.

---

## Доступ и учётные данные

- **Стандартный доступ:** `http://<IP_сервера>:8080`
- **Через Visiology:** `http://<IP_платформы>/v3/zabbix` (если при установке была включена интеграция с конфигом Visiology)
- **Логин:** `Admin`
- **Пароль по умолчанию:** `zabbix` (рекомендуется сменить при первом входе: User settings → Change password)

---

## Устранение неполадок

### Агент недоступен

Сервер опрашивает агент из контейнера (пассивные проверки), поэтому агент должен принимать подключения с подсети Docker. В `docker-compose.yml` у сервиса `zabbix-agent2` должно быть задано:

```yaml
ZBX_SERVER_HOST: 127.0.0.1,172.16.0.0/12
```

После изменения выполните `docker compose up -d` и `docker restart zabbix-agent2`. Убедитесь, что порт 10050 на хосте открыт и контейнер агента запущен. В Zabbix у хоста **Visiology-Server** в интерфейсе Agent должен быть указан **IP сервера** (на котором крутится агент) и порт **10050**.

### Docker failed to fetch info data

Ошибка возникает, когда процесс zabbix-agent2 в контейнере (по умолчанию пользователь `zabbix`) не может читать `/var/run/docker.sock`. В `docker-compose.yml` у сервиса `zabbix-agent2` добавьте запуск от root:

```yaml
user: "0:0"
```

Затем выполните `docker compose up -d` и `docker restart zabbix-agent2`. После этого элементы шаблона «Docker by Zabbix agent 2» должны начать получать данные.

### Ошибка импорта шаблона: «unsupported version number»

Шаблон экспортирован из несовместимой версии Zabbix. Решения:

- Использовать шаблоны для Zabbix 7.x с [официального репозитория](https://git.zabbix.com/projects/ZBX/repos/zabbix/browse/templates) (ветка `release/7.0` или актуальная для 7.4).
- Либо вручную изменить в файле шаблона тег версии на `7.0` или `7.4` (в XML: `<version>7.0</version>` внутри `<zabbix_export>`, в YAML: `version: '7.0'`).

### Цикл редиректов или скачивание zabbix.php при доступе по /v3/zabbix

В контейнере zabbix-web должен монтироваться кастомный `nginx_http_d.conf` (с обработкой пути `/v3/zabbix/` и передачей полного REQUEST_URI в PHP). Проверьте, что в каталоге установки есть файл `nginx_http_d.conf` из репозитория (режим /v3/zabbix), а в `docker-compose.yml` указан объём `./nginx_http_d.conf:/etc/nginx/http.d/nginx.conf:ro`. В конфиге reverse proxy Visiology для Zabbix должен использоваться `proxy_pass` **без** завершающего слеша.

---

## Обновление после git pull

На сервере после `git pull` обновите каталог установки (например `~/zabbix`): скопируйте туда обновлённый `docker-compose.yml` из репозитория, затем выполните `docker compose up -d` и `docker restart zabbix-agent2`.

---

## Полезные команды

| Действие | Команда |
|----------|---------|
| Остановить Zabbix | `cd ~/zabbix && docker compose down` |
| Запустить снова | `cd ~/zabbix && docker compose up -d` |
| Логи веб-интерфейса | `docker compose logs -f zabbix-web` |
| Логи сервера | `docker compose logs -f zabbix-server` |
| Логи агента | `docker compose logs -f zabbix-agent2` |
| Проверка порта агента | `nc -zv 127.0.0.1 10050` |

---

Подробное описание шагов, настройки триггеров, повторного развёртывания и структуры файлов см. в **zabbix_visiology_install.md**.
