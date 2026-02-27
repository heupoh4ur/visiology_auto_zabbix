# Пошаговая установка Zabbix в Docker для мониторинга сервера Visiology

Инструкция для работы **с машины под Linux**: развёртывание Zabbix 7.4 в Docker на сервере с Visiology, мониторинг компонентов Visiology, Docker Swarm, сети, диска (warning при свободном месте &lt; 25%) и доступ по **http://&lt;IP&gt;/v3/zabbix** через reverse proxy.

Все файлы лежат в корне репозитория. После клонирования перейдите в каталог репозитория и запускайте установщик или копируйте файлы оттуда.

---

## 0. Установка одним скриптом (рекомендуется)

Скрипт **install-zabbix.sh** в корне репозитория выполняет установку Zabbix в Docker и при необходимости настройку через API и интеграцию с Visiology.

**Запуск на сервере** (из каталога репозитория после клонирования):

```bash
chmod +x install-zabbix.sh
./install-zabbix.sh
```

Скрипт интерактивно спросит:

- **Каталог установки** (по умолчанию `~/zabbix`).
- **IP или хост сервера** — адрес доступа к Zabbix (по умолчанию определяется автоматически).
- **IP для опроса агента** — адрес, с которого сервер в Docker подключается к агенту (по умолчанию **авто**: Docker bridge, обычно 172.17.0.1; можно задать вручную).
- **Режим доступа:** 1) стандартный (**http://IP:8080**) или 2) по пути **/v3/zabbix** (**http://IP/v3/zabbix**).
- При выборе /v3/zabbix — **вносить ли изменения в конфиги Visiology** (добавить блок в reverse proxy) или оставить Zabbix внешним компонентом.
- **Выполнять ли настройку через API** (хост, шаблоны, триггер, дашборд «Главный экран»; по умолчанию да).

**Режим отладки** (понять, на каком этапе произошла ошибка):

```bash
./install-zabbix.sh -d
```

При `-d` выводится подробный лог каждого шага, анимация отключена.

**Неинтерактивный запуск** (например из CI или при отсутствии TTY): задайте переменные окружения:

```bash
INSTALL_DIR=~/zabbix URL_MODE=standard DO_API_CONFIG=1 ./install-zabbix.sh
# или
URL_MODE=v3zabbix VISIOLOGY_INTEGRATE=1 DO_API_CONFIG=1 SERVER_IP=192.168.31.100 ./install-zabbix.sh
```

- `SERVER_IP` — IP или хост, по которому доступен Zabbix (если не задан — определяется автоматически).
- `ZABBIX_AGENT_IP` — IP для опроса агента сервером из Docker (по умолчанию авто: 172.17.0.1 или из docker0).
- `URL_MODE=standard` — доступ по **http://IP:8080**; `URL_MODE=v3zabbix` — по **http://IP/v3/zabbix**.
- `VISIOLOGY_INTEGRATE=1` — добавить /v3/zabbix в конфиг Visiology (имеет смысл только при `URL_MODE=v3zabbix`).
- `DO_API_CONFIG=0` — не выполнять настройку через API.

После успешного запуска скрипта разделы 2–4.1 (подготовка файлов, первый вход, настройка прокси при /v3/zabbix) и при включённой настройке по API — разделы 5–7 можно не выполнять.

---

## 1. Требования

- Рабочая машина и/или сервер под **Linux** с установленными Docker и Docker Compose (Compose V2: `docker compose`).
- На сервере Zabbix: порты свободны **8080** (веб), **10051** (сервер), **10050** (агент, при необходимости).
- Доступ по SSH к серверу с рабочей машины (для копирования файлов и при необходимости запуска команд).

---

## 2. Подготовка файлов на сервере

### 2.1. Создание каталога

На целевом сервере выполните (если есть права на `/opt`):

```bash
sudo mkdir -p /opt/zabbix
sudo chown $USER:$USER /opt/zabbix
cd /opt/zabbix
```

Если прав на `/opt` нет — используйте домашний каталог:

```bash
mkdir -p ~/zabbix
cd ~/zabbix
```

Далее в инструкции везде подразумевается выбранный каталог (например `~/zabbix` или `/opt/zabbix`).

### 2.2. Копирование docker-compose, nginx_http_d.conf и .env

Если используете скрипт **install-zabbix.sh** (раздел 0), выполните на сервере `git clone` репозитория (или скопируйте каталог на сервер), затем `chmod +x install-zabbix.sh` и `./install-zabbix.sh`.

Вручную (без скрипта): с рабочей машины под Linux скопируйте файлы на сервер. Замените `РЕПО` на имя каталога репозитория, `IP_СЕРВЕРА` и имя пользователя при необходимости. Если планируете автоматическую настройку (п. 4.2), добавьте в команду `scp` файлы `zabbix-init-config.py`, `zabbix-init-config.env`, каталог `agent2.d` (с файлами `98_docker_commands.conf` и `99_server_active.conf`) и `Dockerfile.agent2` (образ с curl, jq и docker-cli — виджеты docker service ls, docker ps, диск).

```bash
scp -P 22 РЕПО/docker-compose.yml РЕПО/nginx_http_d.conf РЕПО/.env.example USER@IP_СЕРВЕРА:~/zabbix/
```
При использовании п. 4.2 и виджетов дашборда (контейнеры, Swarm) добавьте: `РЕПО/zabbix-init-config.py`, `РЕПО/zabbix-init-config.env`, `scp -r РЕПО/agent2.d USER@IP_СЕРВЕРА:~/zabbix/`, `scp РЕПО/Dockerfile.agent2 USER@IP_СЕРВЕРА:~/zabbix/`.

На сервере:

```bash
cd ~/zabbix
cp .env.example .env
# При необходимости отредактируйте .env (пароли, ZBX_HOSTNAME, TZ, ZBX_FRONTEND_URL для /v3/zabbix)
nano .env
```

Если копировать неоткуда — создайте на сервере вручную `docker-compose.yml`, `nginx_http_d.conf` и `.env` по содержимому из репозитория (для `.env` скопируйте `.env.example` и переименуйте).

---

## 3. Запуск Zabbix

Если устанавливали через **install-zabbix.sh**, скрипт уже скопировал `Dockerfile.agent2`, собрал образ `zabbix-agent2-with-curl` и выполнил `docker compose up -d`. Дальнейшие шаги — только при ручной установке.

При **ручной установке** перед первым запуском соберите образ агента с curl (для виджетов «Запущенные контейнеры», «Exited контейнеры», «Состояние Docker Swarm»):

```bash
cd ~/zabbix
# или  cd /opt/zabbix
docker build -f Dockerfile.agent2 -t zabbix-agent2-with-curl .
# В образе: curl, jq, docker-cli (для вывода docker service ls и docker ps в виджетах).
```

Если `Dockerfile.agent2` нет или сборка не нужна, в `.env` добавьте: `ZABBIX_AGENT2_IMAGE=zabbix/zabbix-agent2:alpine-7.4-latest` — тогда виджеты Docker/Swarm будут показывать «No data».

Запуск контейнеров:

```bash
cd ~/zabbix
# или  cd /opt/zabbix
docker compose up -d
```

Проверка:

```bash
docker compose ps
```

Должны быть в состоянии **Up**: `zabbix-postgres`, `zabbix-server`, `zabbix-web`, `zabbix-agent2`.

Первый запуск базы и веб-интерфейса может занять 1–2 минуты. Логи:

```bash
docker compose logs -f zabbix-server
# или
docker compose logs -f zabbix-web
```

---

## 4. Первый вход в веб-интерфейс

1. Откройте в браузере: **http://&lt;IP_сервера&gt;:8080**  
   Пример: `http://192.168.31.100:8080`
2. Логин: **Admin**  
   Пароль: **zabbix**
3. Сразу смените пароль: **User settings** (иконка пользователя) → **Change password**.

---

## 4.1. Доступ к Zabbix по адресу &lt;IP платформы&gt;/v3/zabbix

Чтобы открывать веб-интерфейс Zabbix по пути **http://&lt;IP платформы&gt;/v3/zabbix** (через reverse proxy Visiology, без отдельного порта 8080), нужно добавить в конфиг прокси блок для Zabbix и обновить сервис.

**Где настраивать:** на том же сервере, где работает стек Visiology. Конфиг подключается к сервису `visiology_reverse-proxy` (порт 80).

### Шаги

1. **Подключитесь по SSH к серверу** с Visiology и перейдите в каталог скриптов:
   ```bash
   cd /var/lib/visiology/scripts
   ```

2. **Сделайте резервную копию** текущего конфига (если ещё не делали):
   ```bash
   cp configs/v3include.conf configs/v3include.conf.bak
   ```

3. **Откройте конфиг** `configs/v3include.conf` и добавьте в конец файла блок (подставьте **реальный IP вашего сервера** вместо `192.168.31.100`, если он другой).  
   **Важно:** конфиг обрабатывается движком шаблонов Golang, поэтому все nginx-переменные нужно писать как `{{ "$" }}имя`. В `proxy_pass` **не ставьте** слеш в конце (`v3_zabbix_url` без `/`), чтобы на бэкенд уходил полный путь `/v3/zabbix/...` — тогда в контейнере zabbix-web (с кастомным `nginx_http_d.conf`) PHP получит правильный REQUEST_URI и не будет циклического редиректа. Строки **proxy_redirect** нужны, чтобы редиректы после входа переписывались в `/v3/zabbix/...`: первые две — для абсолютных и относительных путей с ведущим `/`, две с регулярными выражениями — для относительных заголовков вида `zabbix.php?action=...` и `index.php?...`, иначе браузер зацикливается. При другом IP замените `192.168.31.100:8080` в первой строке proxy_redirect.
   ```nginx
   # Zabbix: доступ по /v3/zabbix/ ($ через {{ "$" }} для Go-шаблона)
   set {{ "$" }}v3_zabbix_url http://192.168.31.100:8080;
   location = /v3/zabbix { return 301 {{ "$" }}scheme://{{ "$" }}host/v3/zabbix/; }
   location ~* ^/v3/zabbix/ {
       proxy_pass {{ "$" }}v3_zabbix_url;
       proxy_http_version 1.1;
       proxy_redirect http://192.168.31.100:8080/ /v3/zabbix/;
       proxy_redirect / /v3/zabbix/;
       proxy_redirect ~^zabbix\.php(.*)$ /v3/zabbix/zabbix.php{{ "$" }}1;
       proxy_redirect ~^index\.php(.*)$ /v3/zabbix/index.php{{ "$" }}1;
       proxy_set_header Host {{ "$" }}host;
       proxy_set_header X-Real-IP {{ "$" }}remote_addr;
       proxy_set_header X-Forwarded-For {{ "$" }}proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto {{ "$" }}scheme;
       proxy_set_header X-Forwarded-Host {{ "$" }}host;
       proxy_set_header X-Forwarded-Prefix /v3/zabbix;
       sub_filter 'href="/' 'href="/v3/zabbix/';
       sub_filter 'src="/'  'src="/v3/zabbix/';
       sub_filter 'action="/' 'action="/v3/zabbix/';
       sub_filter_once off;
       sub_filter_types text/html application/json;
   }
   ```

4. **Пересоздайте Docker config** и обновите сервис reverse-proxy (выполнять из `/var/lib/visiology/scripts`):
   ```bash
   docker config rm v3include
   docker config create v3include --template-driver golang ./configs/v3include.conf
   docker service update visiology_reverse-proxy --config-add source=v3include,target=/etc/nginx/platform_conf/v3include.conf
   ```
   Если при `service update` появляется ошибка про «port already in use», подождите 1–2 минуты и выполните `docker service update ...` ещё раз — сервис должен сойтись после переразвёртывания.

5. **Проверьте доступ:** откройте в браузере **http://&lt;IP платформы&gt;/v3/zabbix** (или **http://&lt;IP платформы&gt;/v3/zabbix/**). Должен открыться интерфейс входа Zabbix. Логин и пароль — как в разделе 4.

6. **Чтобы не было «too many redirects» после входа:** в контейнере zabbix-web должен использоваться кастомный nginx-конфиг, который обрабатывает путь `/v3/zabbix/` и передаёт в PHP полный **REQUEST_URI** (`/v3/zabbix/zabbix.php?…`). Тогда Zabbix считает запрос уже «каноничным» и не отдаёт 302 на тот же URL. Для этого в `docker-compose` к сервису `zabbix-web` добавлен объём: `./nginx_http_d.conf:/etc/nginx/http.d/nginx.conf:ro`, а в блоке прокси для Zabbix используется **proxy_pass без слеша в конце** (`v3_zabbix_url` без `/`), чтобы на бэкенд уходил полный путь `/v3/zabbix/...`. Файл `nginx_http_d.conf` лежит в той же папке, что и `docker-compose.yml`. Дополнительно в Zabbix можно задать **Administration** → **General** → **Other** → **Frontend URL** = `http://<IP платформы>/v3/zabbix`.

**Повторное развёртывание на другой машине:** если Zabbix и прокси переносятся на другой сервер, в блоке выше замените `192.168.31.100` на IP нового сервера (где слушает Zabbix web на порту 8080), сохраните конфиг, снова выполните шаги 4–5.

### 4.2. Автоматическая настройка через скрипт (хост, шаблоны, триггер)

Все надстройки (группа, хост с агентом, шаблоны **Linux by Zabbix agent 2** и **Docker by Zabbix agent 2**, триггер «свободно места на диске меньше 25%») можно внести одной командой через Zabbix API.

1. **Скопируйте на сервер** (или на машину с доступом к Zabbix) файлы из корня репозитория:
   - `zabbix-init-config.py`
   - `zabbix-init-config.env`
2. **Настройте параметры:** скопируйте `zabbix-init-config.env` в `zabbix-init-config.local.env` и задайте:
   - **ZABBIX_URL** — URL веб-интерфейса (например `http://192.168.31.100:8080`);
   - **ZABBIX_USER** / **ZABBIX_PASSWORD** — логин и пароль (по умолчанию Admin / zabbix);
   - **ZBX_HOSTNAME** — имя хоста (должно совпадать с `ZBX_HOSTNAME` в `.env` контейнера агента, по умолчанию `Visiology-Server`);
   - **ZABBIX_AGENT_IP** — IP, по которому сервер подключается к агенту (IP сервера, например `192.168.31.100`, или `127.0.0.1`).
3. **Запустите скрипт** (из каталога, где лежат файлы):
   ```bash
   python3 zabbix-init-config.py
   ```
   Либо предварительно загрузите переменные:  
   `set -a && source zabbix-init-config.local.env && set +a && python3 zabbix-init-config.py`  
   Скрипт сам подхватит `zabbix-init-config.local.env` или `zabbix-init-config.env`, если он в той же папке.
4. После успешного выполнения в Zabbix будут созданы группа **Visiology**, хост с интерфейсом агента, подключены шаблоны Linux и Docker и добавлен триггер по свободному месту на диске. Разделы 5–7 можно пропустить.

---

## 5. Добавление хоста «Visiology Server» (вручную)

Если вы использовали скрипт из п. 4.2, переходите к разделу 8.

1. **Data collection** → **Hosts** → **Create host**.
2. Укажите:
   - **Host name:** `Visiology-Server` (или как в `ZBX_HOSTNAME` в `.env`).
   - **Groups:** создать группу **Visiology** (или выбрать существующую).
   - **Interfaces:** тип **Agent**, **IP address:** IP вашего сервера (например `192.168.31.100`), **Port:** `10050`.
   - **Host inventory:** при необходимости включите автоматическое заполнение.
3. Сохраните (**Add**).

---

## 6. Подключение шаблонов к хосту

Шаблоны **Linux by Zabbix agent 2** и **Docker by Zabbix agent 2** входят в поставку Zabbix 7.4 — их не нужно скачивать и импортировать, они уже есть в системе.

1. Откройте созданный хост → вкладка **Templates**.
2. **Select** и добавьте шаблоны из списка:
   - **Linux by Zabbix agent 2** — CPU, память, диск, сеть, процессы.
   - **Docker by Zabbix agent 2** — контейнеры, образы, Docker/Swarm (требуется доступ к `/var/run/docker.sock`, уже настроен в агенте).
3. **Add** → **Update**.

Через 1–2 минуты на вкладке **Latest data** появятся данные. **«Агент недоступен»:** в `docker-compose` для агента должно быть `ZBX_SERVER_HOST: 127.0.0.1,172.16.0.0/12`, затем `docker compose up -d` и `docker restart zabbix-agent2`; у хоста в Zabbix в интерфейсе Agent укажите IP сервера и порт 10050. **«Docker failed to fetch info data»:** у сервиса `zabbix-agent2` в compose должен быть `user: "0:0"` (доступ к docker.sock), затем перезапустите агент.

### 6.1. Импорт своих шаблонов и ошибка «unsupported version number»

Если вы скачали шаблон извне и при импорте появляется **Invalid tag "/zabbix_export/version": unsupported version number**, файл экспортирован из несовместимой версии Zabbix (старее 6.0 или новее 7.4, либо другой формат).

**Что сделать:**

- **Брать шаблоны для Zabbix 7.x** с официального репозитория:  
  **https://git.zabbix.com/projects/ZBX/repos/zabbix/browse/templates** — выберите ветку `release/7.0` или актуальную для 7.4, скачайте нужный шаблон в формате XML/YAML.
- **Либо поправить версию в уже скачанном файле:** откройте файл шаблона (XML, YAML или JSON) и замените тег версии на поддерживаемую. Для Zabbix 7.4 подходят версии **7.0** или **7.4**.
  - **XML:** найдите `<version>...</version>` внутри `<zabbix_export>` и поставьте, например, `<version>7.0</version>`.
  - **YAML:** в блоке `zabbix_export:` замените `version: '...'` на `version: '7.0'` или `version: '7.4'`.
  - **JSON:** в объекте `zabbix_export` замените поле `"version"` на `"7.0"` или `"7.4"`.
- После сохранения файла повторите импорт: **Data collection** → **Templates** → **Import**.

---

## 7. Триггер «Свободно места на диске меньше 25%» (Warning)

Цель: срабатывание предупреждения, когда свободного места остаётся меньше 25% (т.е. занято более 75%).

### 7.1. Через веб-интерфейс

1. **Data collection** → **Hosts** → выберите хост **Visiology-Server**.
2. **Triggers** → **Create trigger**.
3. Заполните:
   - **Name:** `Диск {#FSNAME}: свободно меньше 25% на {HOST.NAME}`
   - **Expression:** конструктор выражений:
     - **Item:** выберите элемент вида **Free disk space on {#FSNAME}** (или **vfs.fs.size[/hostfs,pfree]** для корня).
       Если такого нет — сначала убедитесь, что к хосту подключён шаблон **Linux by Zabbix agent 2** и что в шаблоне есть item для свободного места (в процентах, pfree). Либо создайте Item вручную:
       - Key: `vfs.fs.size[/hostfs,pfree]`
       - Type: Numeric (float)
       - Units: %
     - **Function:** **last()** (или **avg()** за последние 5 мин).
     - **Numeric:** **&lt; 25**
   - **Severity:** **Warning**.
   - **OK event generation:** при необходимости выберите **Recovery expression** (например, когда pfree снова &gt; 25).
4. **Add** → **Update**.

### 7.2. Выражение триггера вручную (если знаете key item)

Пример для одного раздела (корень, смонтированный в контейнере как `/hostfs`):

- Имя item (если создаёте вручную): `Free disk space on / (percentage)`
- Key: `vfs.fs.size[/hostfs,pfree]`
- Триггер expression:  
  `last(/Visiology-Server/vfs.fs.size[/hostfs,pfree])&lt;25`

Severity: **Warning**.

### 7.3. Несколько разделов (discovery)

Если используется **Template Linux by Zabbix agent 2**, в нём обычно есть **Filesystem discovery** и элементы с `vfs.fs.size[{#FSNAME},pfree]`. В этом случае триггер с макросом:

- **Name:** `Диск {#FSNAME}: свободно меньше 25%`
- **Expression:**  
  `last(/Visiology-Server/vfs.fs.size[{#FSNAME},pfree])&lt;25`
- **Severity:** Warning.

При необходимости замените `Visiology-Server` на фактическое имя хоста в Zabbix.

---

## 8. Мониторинг Docker Swarm и контейнеров Visiology

- Шаблон **Docker by Zabbix agent 2** даёт:
  - количество контейнеров (running/stopped),
  - образы,
  - данные по Docker Engine.
- Для Swarm дополнительно можно использовать низкоуровневые метрики Docker (если они доступны через тот же агент с доступом к `docker.sock`).
- Контейнеры Visiology (например, `visiology3_*`) отображаются как часть мониторинга Docker; при необходимости создайте отдельные триггеры по имени контейнера или по тегам (например, по label `component`).

При желании можно создать отдельную группу хостов **Visiology** и использовать пользовательские дашборды или триггеры по обнаруженным контейнерам.

---

## 9. Дополнительные настройки (по желанию)

- **Сеть:** загрузка интерфейсов уже собирается шаблоном **Linux by Zabbix agent 2** (net.if.*). При необходимости настройте фильтры discovery по интерфейсам.
- **Уведомления:** **Alerts** → **Actions** — настройте доставку (Email, Telegram, и т.д.) для триггеров с Severity Warning/High.
- **Дашборды:** **Reports** → **Dashboards** — создайте дашборд для хоста Visiology-Server и добавьте виджеты: CPU, память, диск, сеть, Docker (контейнеры/образы).

---

## 10. Повторное развёртывание на другой машине с Visiology

Чтобы развернуть такой же Zabbix на **другом** сервере с Visiology (с машины под Linux):

1. Убедитесь, что на целевом сервере установлены Docker и Docker Compose.
2. Клонируйте репозиторий на новый сервер (или скопируйте каталог). Файлы для установки — в корне клонированного каталога.
   На целевом сервере: `cd ~/zabbix && cp .env.example .env` (если устанавливаете вручную) и отредактируйте `.env` (ZBX_HOSTNAME, TZ, пароли, при доступе по /v3/zabbix — ZBX_FRONTEND_URL).
3. Запустите Zabbix (или выполните `./install-zabbix.sh` из каталога репозитория):
   ```bash
   cd ~/zabbix
   docker compose up -d
   ```
4. Откройте веб-интерфейс: `http://<IP_нового_сервера>:8080`.
5. Повторите шаги **4–8** данной инструкции для нового хоста (указав IP нового сервера при добавлении хоста и при создании триггера по диску).
6. Если на новой машине другой путь к корню или другие разделы — при создании item/триггера по диску используйте соответствующие пути (при монтировании хоста в контейнер агента как `/hostfs` ключ для корня остаётся `vfs.fs.size[/hostfs,pfree]`).
7. Если нужен доступ к Zabbix по **&lt;IP&gt;/v3/zabbix**, выполните шаги раздела **4.1** на целевом сервере, указав в блоке конфига прокси IP нового сервера вместо 192.168.31.100.

---

## 11. Полезные команды

| Действие | Команда |
|----------|---------|
| Остановить Zabbix | `cd ~/zabbix && docker compose down` |
| Запустить снова | `cd ~/zabbix && docker compose up -d` |
| Логи сервера | `docker compose logs -f zabbix-server` |
| Логи агента | `docker compose logs -f zabbix-agent2` |
| Проверка агента с хоста | `nc -zv 127.0.0.1 10050` или `docker exec zabbix-agent2 zabbix_agent2 -t agent.hostname` |

---

## 12. Структура файлов в репозитории

Все файлы в **корне** каталога репозитория:

- **docker-compose.yml** — сервисы: PostgreSQL, Zabbix Server, Zabbix Web (Nginx), Zabbix Agent 2 (с монтированием `/` в `/hostfs` и `docker.sock` для мониторинга хоста и Docker). У агента: `ZBX_SERVER_HOST: 127.0.0.1,172.16.0.0/12` (принимать пассивные проверки от сервера в контейнере), `user: "0:0"` (доступ к docker.sock, иначе «Docker failed to fetch info data»). Для доступа по /v3/zabbix в zabbix-web монтируется `nginx_http_d.conf`.
- **zabbix-init-config.env** — пример переменных для скрипта автоматической настройки (URL, логин, имя хоста, IP агента). Копируется в `zabbix-init-config.local.env` и при необходимости редактируется.
- **zabbix-init-config.py** — скрипт настройки Zabbix через API: создаёт группу, хост с агентом, подключает шаблоны **Linux by Zabbix agent 2** и **Docker by Zabbix agent 2**, добавляет триггер «свободно места на диске меньше 25%» и дашборд **«Главный экран»** с виджетами: проблемы по важности, список запущенных контейнеров (аналог docker ps), только exited-контейнеры, заполненность диска (%), состояние Docker Swarm. Запуск: `python3 zabbix-init-config.py` (см. п. 4.2).
- **install-zabbix.sh** — установка «в один клик»: копирует файлы, поднимает контейнеры, при необходимости настраивает Zabbix через API и добавляет /v3/zabbix в Visiology. Запуск: `./install-zabbix.sh` (интерактивно) или `./install-zabbix.sh -d` (отладка). Параметры через переменные: `INSTALL_DIR`, `URL_MODE`, `DO_API_CONFIG`, `VISIOLOGY_INTEGRATE`, `SERVER_IP` (см. раздел 0).
- **nginx_http_d_standard.conf** — конфиг nginx для режима доступа по **http://IP:8080** (без префикса /v3/zabbix); используется скриптом при `URL_MODE=standard`.
- **nginx_http_d.conf** — кастомный конфиг nginx в контейнере zabbix-web: обработка пути `/v3/zabbix/` (PHP с полным REQUEST_URI и статика), чтобы не было циклических редиректов и скачивания zabbix.php.
- **.env.example** — пример переменных (пароли, порты, имя хоста, TZ, при /v3/zabbix — ZBX_FRONTEND_URL); копируется в `.env` на сервере.

Официальные шаблоны для Zabbix 7.x (в т.ч. для импорта): https://git.zabbix.com/projects/ZBX/repos/zabbix/browse/templates (ветка release/7.0 или текущая для 7.4).

После выполнения шагов 1–8 у вас будет работающий Zabbix с мониторингом компонентов Visiology, состояния Swarm, сети, диска с предупреждением при свободном месте меньше 25%. Доступ по **http://&lt;IP&gt;/v3/zabbix** настраивается в разделе 4.1.
