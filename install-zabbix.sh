#!/usr/bin/env bash
# Установка Zabbix 7.4 в Docker с опциональной настройкой через API и интеграцией в Visiology.
#
# Запуск:
#   ./install-zabbix.sh       — интерактивно запросит параметры
#   ./install-zabbix.sh -d   — режим отладки (подробный вывод, без анимации)
#
# Неинтерактивный режим (без TTY): задайте переменные и запустите скрипт:
#   INSTALL_DIR=~/zabbix URL_MODE=standard DO_API_CONFIG=1 ./install-zabbix.sh
#   URL_MODE=v3zabbix — доступ по http://IP/v3/zabbix
#   VISIOLOGY_INTEGRATE=1    — добавить /v3/zabbix в конфиг Visiology (только при URL_MODE=v3zabbix)
#   DO_API_CONFIG=0          — не выполнять настройку через API (по умолчанию 1)
#   SERVER_IP=192.168.1.1    — IP/хост для доступа к Zabbix (веб, редиректы)
#   ZABBIX_AGENT_IP=172.17.0.1 — IP, по которому сервер в Docker опрашивает агента (по умолчанию авто: docker bridge)
set -e

DEBUG=0
while getopts "d" opt; do
  case "$opt" in
    d) DEBUG=1 ;;
    *) echo "Использование: $0 [-d]" >&2; exit 1 ;;
  esac
done

if [ "$DEBUG" -eq 1 ]; then
  set -x
fi

# Каталог, откуда запущен скрипт (ожидается, что рядом лежат docker-compose.yml, nginx_http_d*.conf и т.д.)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Каталог установки Zabbix (по умолчанию ~/zabbix)
INSTALL_DIR="${INSTALL_DIR:-$HOME/zabbix}"
# Режим доступа: standard (http://IP:8080) или v3zabbix (http://IP/v3/zabbix)
URL_MODE="${URL_MODE:-}"
# Выполнять ли настройку через API (хост, шаблоны, триггер): 1 — да, 0 — нет
DO_API_CONFIG="${DO_API_CONFIG:-1}"
# Вносить ли изменения в конфиги Visiology (добавить /v3/zabbix в reverse proxy): 1 — да, 0 — нет
VISIOLOGY_INTEGRATE="${VISIOLOGY_INTEGRATE:-0}"
# IP/хост сервера — для доступа к Zabbix (веб, ZBX_FRONTEND_URL, Visiology)
SERVER_IP="${SERVER_IP:-}"
# IP, по которому сервер в Docker подключается к агенту (обычно gateway docker0, напр. 172.17.0.1). Пусто — авто.
ZABBIX_AGENT_IP="${ZABBIX_AGENT_IP:-}"

# Цвета и сброс
R="\033[0;31m"
G="\033[0;32m"
Y="\033[1;33m"
N="\033[0m"

# Спиннер в фоне (PID в SPINNER_PID); остановить через stop_spinner
SPINNER_PID=""
spinner_start() {
  [ "$DEBUG" -eq 1 ] && return
  (
    while true; do
      for c in '⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏'; do
        printf '\r  %s %s' "$c" "$1"
        sleep 0.08
      done
    done
  ) &
  SPINNER_PID=$!
}

stop_spinner() {
  [ -z "$SPINNER_PID" ] && return
  kill "$SPINNER_PID" 2>/dev/null || true
  wait "$SPINNER_PID" 2>/dev/null || true
  SPINNER_PID=""
  printf '\r\033[K'
}

log_step() {
  if [ "$DEBUG" -eq 1 ]; then
    echo "[$(date '+%H:%M:%S')] $*"
  else
    printf '\r\033[K'
    echo -e "${G}[*]${N} $*"
  fi
}

log_err() {
  echo -e "${R}[!]${N} $*" >&2
}

log_warn() {
  echo -e "${Y}[~]${N} $*"
}

# Определение IP сервера (для веб-доступа и .env)
detect_server_ip() {
  if [ -n "$SERVER_IP" ]; then
    return
  fi
  if command -v hostname >/dev/null 2>&1; then
    SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  if [ -z "$SERVER_IP" ] && [ -r /proc/net/route ]; then
    SERVER_IP="$(ip -4 route get 8.8.8.8 2>/dev/null | grep -oP 'src \K\S+' || true)"
  fi
  if [ -z "$SERVER_IP" ]; then
    SERVER_IP="127.0.0.1"
  fi
}

# IP Docker bridge (gateway docker0) — с контейнера сервер по нему достучится до агента на хосте
detect_docker_bridge_ip() {
  if [ -n "$ZABBIX_AGENT_IP" ]; then
    return
  fi
  if command -v ip >/dev/null 2>&1; then
    ZABBIX_AGENT_IP="$(ip -4 addr show docker0 2>/dev/null | grep -oP 'inet \K[\d.]+' | head -1)"
  fi
  if [ -z "$ZABBIX_AGENT_IP" ] && command -v docker >/dev/null 2>&1; then
    ZABBIX_AGENT_IP="$(docker network inspect bridge 2>/dev/null | grep -oP '"Gateway": "\K[^"]+' | head -1)"
  fi
  if [ -z "$ZABBIX_AGENT_IP" ]; then
    ZABBIX_AGENT_IP="172.17.0.1"
  fi
}

# Интерактивный ввод, если не задано переменными
prompt_if_empty() {
  local var_name="$1"
  local prompt_text="$2"
  local default_val="$3"
  local val="${!var_name}"
  if [ -z "$val" ]; then
    if [ -t 0 ]; then
      read -p "$prompt_text [$default_val]: " val
      val="${val:-$default_val}"
    else
      val="$default_val"
    fi
    eval "$var_name=\"$val\""
  fi
}

# --- Приветствие и запрос параметров ---
echo ""
echo "  Zabbix 7.4 — установка в Docker (Visiology / автономно)"
echo "  ---------------------------------------------------------"
echo ""

if [ -t 0 ]; then
  prompt_if_empty INSTALL_DIR "Каталог установки" "$HOME/zabbix"
  if [ -z "$URL_MODE" ]; then
    echo "  Режим доступа к веб-интерфейсу:"
    echo "    1) Стандартный (http://IP:8080)"
    echo "    2) Через путь /v3/zabbix (http://IP/v3/zabbix)"
    read -p "  Выбор [1]: " url_choice
    url_choice="${url_choice:-1}"
    if [ "$url_choice" = "2" ]; then
      URL_MODE="v3zabbix"
    else
      URL_MODE="standard"
    fi
  fi
  if [ "$URL_MODE" = "v3zabbix" ]; then
    if [ -z "$VISIOLOGY_INTEGRATE" ] || [ "$VISIOLOGY_INTEGRATE" != "1" ]; then
      read -p "  Добавить Zabbix в конфиг Visiology (reverse proxy /v3/zabbix)? [y/N]: " vi_choice
      if [[ "$vi_choice" =~ ^[yYдД] ]]; then
        VISIOLOGY_INTEGRATE=1
      else
        VISIOLOGY_INTEGRATE=0
      fi
    fi
  else
    VISIOLOGY_INTEGRATE=0
  fi
  if [ -z "$DO_API_CONFIG" ] || [ "$DO_API_CONFIG" != "0" ]; then
    read -p "  Выполнить настройку через API (хост, шаблоны, триггер)? [Y/n]: " api_choice
    if [[ "$api_choice" =~ ^[nNтТ] ]]; then
      DO_API_CONFIG=0
    else
      DO_API_CONFIG=1
    fi
  fi
else
  INSTALL_DIR="${INSTALL_DIR:-$HOME/zabbix}"
  URL_MODE="${URL_MODE:-standard}"
  [ -z "$URL_MODE" ] && URL_MODE="standard"
  [ "$URL_MODE" != "v3zabbix" ] && VISIOLOGY_INTEGRATE=0
  DO_API_CONFIG="${DO_API_CONFIG:-1}"
fi

detect_server_ip
prompt_if_empty SERVER_IP "IP или хост сервера (адрес доступа к Zabbix, для .env и Visiology)" "$SERVER_IP"
detect_docker_bridge_ip
if [ -t 0 ] && [ -z "${ZABBIX_AGENT_IP_FROM_ENV:-}" ]; then
  read -p "  IP для опроса агента сервером (Docker bridge, обычно 172.17.0.1) [${ZABBIX_AGENT_IP}]: " agent_ip_choice
  if [ -n "$agent_ip_choice" ]; then
    ZABBIX_AGENT_IP="$agent_ip_choice"
  fi
fi
export ZABBIX_AGENT_IP

echo ""
log_step "Параметры: каталог=$INSTALL_DIR, URL=$URL_MODE, API=$DO_API_CONFIG, Visiology=$VISIOLOGY_INTEGRATE, IP_сервера=$SERVER_IP, IP_агента=$ZABBIX_AGENT_IP"
echo ""

# --- Создание каталога и копирование файлов ---
log_step "Создание каталога установки и копирование файлов..."
spinner_start "подготовка файлов"
mkdir -p "$INSTALL_DIR"
cp -f "$SCRIPT_DIR/docker-compose.yml" "$INSTALL_DIR/"
cp -f "$SCRIPT_DIR/.env.example" "$INSTALL_DIR/.env"

if [ "$URL_MODE" = "v3zabbix" ]; then
  cp -f "$SCRIPT_DIR/nginx_http_d.conf" "$INSTALL_DIR/nginx_http_d.conf"
else
  cp -f "$SCRIPT_DIR/nginx_http_d_standard.conf" "$INSTALL_DIR/nginx_http_d.conf"
fi

# ZBX_FRONTEND_URL в .env
if [ "$URL_MODE" = "v3zabbix" ]; then
  if grep -q '^ZBX_FRONTEND_URL=' "$INSTALL_DIR/.env" 2>/dev/null; then
    sed -i "s|^ZBX_FRONTEND_URL=.*|ZBX_FRONTEND_URL=http://${SERVER_IP}/v3/zabbix|" "$INSTALL_DIR/.env"
  else
    echo "ZBX_FRONTEND_URL=http://${SERVER_IP}/v3/zabbix" >> "$INSTALL_DIR/.env"
  fi
else
  if grep -q '^ZBX_FRONTEND_URL=' "$INSTALL_DIR/.env" 2>/dev/null; then
    sed -i "s|^ZBX_FRONTEND_URL=.*|ZBX_FRONTEND_URL=http://${SERVER_IP}:8080|" "$INSTALL_DIR/.env"
  else
    echo "ZBX_FRONTEND_URL=http://${SERVER_IP}:8080" >> "$INSTALL_DIR/.env"
  fi
fi

# Файлы для настройки по API
cp -f "$SCRIPT_DIR/zabbix-init-config.py" "$INSTALL_DIR/" 2>/dev/null || true
cp -f "$SCRIPT_DIR/zabbix-init-config.env" "$INSTALL_DIR/" 2>/dev/null || true
# Локальный env для init-config (адрес Zabbix и IP агента для опроса из Docker)
{
  echo "# Сгенерировано установщиком. Для ручного запуска: python3 zabbix-init-config.py"
  echo "ZABBIX_URL=http://${SERVER_IP}:8080"
  echo "ZABBIX_AGENT_IP=${ZABBIX_AGENT_IP:-172.17.0.1}"
} > "$INSTALL_DIR/zabbix-init-config.local.env" 2>/dev/null || true
# Каталог agent2.d (99_server_active.conf, 98_docker_commands.conf для виджетов)
if [ -d "$SCRIPT_DIR/agent2.d" ]; then
  mkdir -p "$INSTALL_DIR/agent2.d"
  cp -f "$SCRIPT_DIR/agent2.d/"*.conf "$INSTALL_DIR/agent2.d/" 2>/dev/null || true
fi
# Dockerfile агента с curl (для виджетов контейнеров/Swarm на дашборде)
cp -f "$SCRIPT_DIR/Dockerfile.agent2" "$INSTALL_DIR/" 2>/dev/null || true
stop_spinner
log_step "Файлы скопированы в $INSTALL_DIR"

# --- Сборка образа агента с curl (для виджетов дашборда) ---
if [ -f "$INSTALL_DIR/Dockerfile.agent2" ]; then
  log_step "Сборка образа агента (zabbix-agent2-with-curl)..."
  spinner_start "docker build"
  if ( cd "$INSTALL_DIR" && docker build -f Dockerfile.agent2 -t zabbix-agent2-with-curl . ); then
    stop_spinner
    log_step "Образ zabbix-agent2-with-curl собран"
  else
    stop_spinner
    log_warn "Сборка образа агента не удалась. Будет использован стандартный образ (виджеты Docker/Swarm могут показывать «No data»)."
    if ! grep -q '^ZABBIX_AGENT2_IMAGE=' "$INSTALL_DIR/.env" 2>/dev/null; then
      echo "ZABBIX_AGENT2_IMAGE=zabbix/zabbix-agent2:alpine-7.4-latest" >> "$INSTALL_DIR/.env"
    fi
  fi
fi

# --- Запуск контейнеров ---
log_step "Запуск Docker Compose..."
spinner_start "docker compose up -d"
(
  cd "$INSTALL_DIR"
  docker compose up -d
)
stop_spinner
log_step "Контейнеры запущены"

# --- Ожидание API Zabbix ---
log_step "Ожидание доступности API Zabbix..."
ZABBIX_API_URL="http://${SERVER_IP}:8080/api_jsonrpc.php"
waited=0
max_wait=120
while [ $waited -lt $max_wait ]; do
  if curl -sf -X POST "$ZABBIX_API_URL" \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"apiinfo.version","params":[],"id":1}' >/dev/null 2>&1; then
    log_step "API доступен"
    break
  fi
  spinner_start "ожидание API (${waited}s)"
  sleep 5
  stop_spinner
  waited=$((waited + 5))
done
if [ $waited -ge $max_wait ]; then
  log_err "API не ответил за ${max_wait} с. Проверьте: docker compose -f $INSTALL_DIR/docker-compose.yml logs"
  exit 1
fi

# --- Настройка через API ---
if [ "$DO_API_CONFIG" -eq 1 ]; then
  log_step "Настройка Zabbix через API (хост, шаблоны, триггер, дашборд)..."
  spinner_start "API: группа, хост, триггер"
  export ZABBIX_URL="http://${SERVER_IP}:8080"
  export ZABBIX_USER="${ZABBIX_USER:-Admin}"
  export ZABBIX_PASSWORD="${ZABBIX_PASSWORD:-zabbix}"
  export ZBX_HOSTNAME="${ZBX_HOSTNAME:-Visiology-Server}"
  export ZABBIX_AGENT_IP="${ZABBIX_AGENT_IP:-172.17.0.1}"
  export ZABBIX_AGENT_PORT="${ZABBIX_AGENT_PORT:-10050}"
  if [ -f "$INSTALL_DIR/zabbix-init-config.py" ]; then
    if command -v python3 >/dev/null 2>&1; then
      (
        cd "$INSTALL_DIR"
        python3 zabbix-init-config.py
      ) || {
        stop_spinner
        log_warn "Не удалось выполнить zabbix-init-config.py (проверьте python3). Настройте хост и шаблоны вручную."
      }
    else
      stop_spinner
      log_warn "python3 не найден. Настройте хост и шаблоны вручную в веб-интерфейсе."
    fi
  else
    stop_spinner
    log_warn "Файл zabbix-init-config.py не найден. Настройте хост и шаблоны вручную."
  fi
  stop_spinner
  log_step "Настройка через API завершена (хост, шаблоны, триггер, дашборд «Главный экран»: проблемы, контейнеры, диск, Swarm)"
fi

# --- Интеграция с Visiology (добавить /v3/zabbix в reverse proxy) ---
if [ "$VISIOLOGY_INTEGRATE" -eq 1 ] && [ "$URL_MODE" = "v3zabbix" ]; then
  VISIOLOGY_SCRIPTS="/var/lib/visiology/scripts"
  V3INCLUDE="$VISIOLOGY_SCRIPTS/configs/v3include.conf"
  log_step "Интеграция с Visiology: добавление /v3/zabbix в конфиг прокси..."

  if [ ! -d "$VISIOLOGY_SCRIPTS" ]; then
    log_warn "Каталог Visiology не найден: $VISIOLOGY_SCRIPTS. Пропуск интеграции. Добавьте блок вручную (см. инструкцию)."
  elif [ ! -f "$V3INCLUDE" ]; then
    log_warn "Файл $V3INCLUDE не найден. Пропуск интеграции."
  else
    spinner_start "Visiology: backup и правка v3include"
    cp -a "$V3INCLUDE" "${V3INCLUDE}.bak.zabbix.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
    ZABBIX_BLOCK='# Zabbix: доступ по /v3/zabbix/ ($ через {{ "$" }} для Go-шаблона)
set {{ "$" }}v3_zabbix_url http://'"${SERVER_IP}"':8080;
location = /v3/zabbix { return 301 {{ "$" }}scheme://{{ "$" }}host/v3/zabbix/; }
location ~* ^/v3/zabbix/ {
    proxy_pass {{ "$" }}v3_zabbix_url;
    proxy_http_version 1.1;
    proxy_redirect http://'"${SERVER_IP}"':8080/ /v3/zabbix/;
    proxy_redirect / /v3/zabbix/;
    proxy_redirect ~^zabbix\.php(.*)$ /v3/zabbix/zabbix.php{{ "$" }}1;
    proxy_redirect ~^index\.php(.*)$ /v3/zabbix/index.php{{ "$" }}1;
    proxy_set_header Host {{ "$" }}host;
    proxy_set_header X-Real-IP {{ "$" }}remote_addr;
    proxy_set_header X-Forwarded-For {{ "$" }}proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto {{ "$" }}scheme;
    proxy_set_header X-Forwarded-Host {{ "$" }}host;
    proxy_set_header X-Forwarded-Prefix /v3/zabbix;
    sub_filter '\''href="/'\'' '\''href="/v3/zabbix/'\'';
    sub_filter '\''src="/'\''  '\''src="/v3/zabbix/'\'';
    sub_filter '\''action="/'\'' '\''action="/v3/zabbix/'\'';
    sub_filter_once off;
    sub_filter_types text/html application/json;
}
'
    if grep -q 'v3/zabbix' "$V3INCLUDE" 2>/dev/null; then
      log_warn "Блок /v3/zabbix уже есть в $V3INCLUDE. Пропуск добавления."
    else
      echo "$ZABBIX_BLOCK" >> "$V3INCLUDE"
      stop_spinner
      log_step "Пересоздание Docker config и обновление сервиса reverse-proxy..."
      spinner_start "docker config + service update"
      (
        cd "$VISIOLOGY_SCRIPTS"
        docker config rm v3include 2>/dev/null || true
        docker config create v3include --template-driver golang ./configs/v3include.conf
        docker service update visiology_reverse-proxy --config-add source=v3include,target=/etc/nginx/platform_conf/v3include.conf
      ) || {
        stop_spinner
        log_warn "Не удалось обновить сервис Visiology. Выполните вручную из $VISIOLOGY_SCRIPTS: docker config rm v3include; docker config create v3include --template-driver golang ./configs/v3include.conf; docker service update visiology_reverse-proxy --config-add source=v3include,target=..."
      }
    fi
    stop_spinner
  fi
  log_step "Интеграция с Visiology завершена (или пропущена)"
fi

# --- Итог ---
echo ""
echo "  ---------------------------------------------------------"
echo -e "  ${G}Установка завершена.${N}"
echo ""
if [ "$URL_MODE" = "v3zabbix" ]; then
  echo "  Веб-интерфейс Zabbix:  http://${SERVER_IP}/v3/zabbix"
  echo "  (прямой порт 8080:    http://${SERVER_IP}:8080)"
else
  echo "  Веб-интерфейс Zabbix:  http://${SERVER_IP}:8080"
fi
echo "  Логин: Admin   Пароль: zabbix"
echo "  Каталог установки:     $INSTALL_DIR"
echo "  Логи:                   cd $INSTALL_DIR && docker compose logs -f"
echo "  ---------------------------------------------------------"
echo ""
