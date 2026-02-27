#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Настройка Zabbix через API: группа, хост с агентом, шаблоны Linux/Docker, триггер «свободно места < 25%»,
дашборд «Главный экран» (проблемы, контейнеры, диск, Swarm).
Запуск: задайте переменные из zabbix-init-config.env и выполните:
  python3 zabbix-init-config.py
Или: source zabbix-init-config.env && python3 zabbix-init-config.py
"""
from __future__ import print_function

import json
import os
import sys
import time
import urllib.request
import urllib.error
import ssl

# Загрузка переменных из .env (если файл есть)
for _env_file in ("zabbix-init-config.local.env", "zabbix-init-config.env"):
    _path = os.path.join(os.path.dirname(os.path.abspath(__file__)), _env_file)
    if os.path.isfile(_path):
        with open(_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    v = v.strip().strip("'\"")
                    if k.strip():
                        os.environ[k.strip()] = v
        break

# --- конфиг из переменных окружения ---
def env(key, default=None):
    return os.environ.get(key, default)

ZABBIX_URL = env("ZABBIX_URL", "http://127.0.0.1:8080").rstrip("/")
ZABBIX_USER = env("ZABBIX_USER", "Admin")
ZABBIX_PASSWORD = env("ZABBIX_PASSWORD", "zabbix")
ZBX_HOSTNAME = env("ZBX_HOSTNAME", "Visiology-Server")
ZABBIX_AGENT_IP = env("ZABBIX_AGENT_IP", "127.0.0.1")
ZABBIX_AGENT_PORT = env("ZABBIX_AGENT_PORT", "10050")
ZABBIX_HOST_GROUP = env("ZABBIX_HOST_GROUP", "Visiology")
ZABBIX_TEMPLATE_LINUX = env("ZABBIX_TEMPLATE_LINUX", "Linux by Zabbix agent 2")
ZABBIX_TEMPLATE_DOCKER = env("ZABBIX_TEMPLATE_DOCKER", "Docker by Zabbix agent 2")

# Триггер: свободно места на диске (корень /hostfs) меньше 25%
TRIGGER_DESCRIPTION = "Диск: свободно меньше 25% на {HOST.NAME}"
TRIGGER_EXPRESSION_TEMPLATE = "last(/{host}/vfs.fs.size[/hostfs,pfree])<25"
TRIGGER_PRIORITY = 3  # Warning

API_URL = ZABBIX_URL + "/api_jsonrpc.php"
REQUEST_HEADERS = {"Content-Type": "application/json"}

# Без проверки SSL для самоподписанных сертификатов (только для внутреннего использования)
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def api_request(method, params, auth=None):
    body = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    headers = dict(REQUEST_HEADERS)
    if auth:
        headers["Authorization"] = "Bearer %s" % auth
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            data = json.loads(err_body)
        except Exception:
            data = {}
        raise RuntimeError("API %s: HTTP %s %s" % (method, e.code, data.get("error", {}).get("data", err_body)))
    if "error" in data:
        raise RuntimeError("API %s: %s" % (method, data["error"].get("data", data["error"])))
    return data.get("result")


def wait_for_api(max_wait=120, step=5):
    print("Ожидание доступности API Zabbix...")
    start = time.time()
    while time.time() - start < max_wait:
        try:
            api_request("apiinfo.version", [])
            print("API доступен.")
            return
        except Exception as e:
            print("  %s" % e)
        time.sleep(step)
    raise RuntimeError("API не ответил за %s с." % max_wait)


def main():
    if not ZABBIX_URL:
        print("Задайте ZABBIX_URL (и при необходимости другие переменные из zabbix-init-config.env).", file=sys.stderr)
        sys.exit(1)

    wait_for_api()

    auth = api_request("user.login", {"username": ZABBIX_USER, "password": ZABBIX_PASSWORD})
    print("Авторизация выполнена.")

    # Группа
    gr = api_request("hostgroup.get", {"filter": {"name": ZABBIX_HOST_GROUP}, "output": ["groupid"]}, auth)
    if gr:
        groupid = gr[0]["groupid"]
        print("Группа '%s' уже есть: %s" % (ZABBIX_HOST_GROUP, groupid))
    else:
        groupid = api_request("hostgroup.create", {"name": ZABBIX_HOST_GROUP}, auth)["groupids"][0]
        print("Создана группа '%s': %s" % (ZABBIX_HOST_GROUP, groupid))

    # Шаблоны
    tpl = api_request(
        "template.get",
        {
            "output": ["templateid", "name"],
            "search": {"name": [ZABBIX_TEMPLATE_LINUX, ZABBIX_TEMPLATE_DOCKER]},
            "searchByAny": True,
        },
        auth,
    )
    template_ids = [x["templateid"] for x in tpl]
    names_found = [x["name"] for x in tpl]
    for need in (ZABBIX_TEMPLATE_LINUX, ZABBIX_TEMPLATE_DOCKER):
        if need not in names_found:
            print("Внимание: шаблон '%s' не найден (проверьте имя)." % need, file=sys.stderr)
    if not template_ids:
        print("Не найдено ни одного шаблона. Создание хоста без шаблонов.", file=sys.stderr)
    else:
        print("Найдены шаблоны: %s" % names_found)

    # Хост
    existing = api_request("host.get", {"filter": {"host": ZBX_HOSTNAME}, "output": ["hostid"]}, auth)
    if existing:
        hostid = existing[0]["hostid"]
        print("Хост '%s' уже есть: %s. Триггер при необходимости будет добавлен." % (ZBX_HOSTNAME, hostid))
    else:
        hostid = api_request(
            "host.create",
            {
                "host": ZBX_HOSTNAME,
                "groups": [{"groupid": groupid}],
                "interfaces": [
                    {
                        "type": 1,
                        "main": 1,
                        "useip": 1,
                        "ip": ZABBIX_AGENT_IP,
                        "dns": "",
                        "port": ZABBIX_AGENT_PORT,
                    }
                ],
                "templates": [{"templateid": tid} for tid in template_ids],
            },
            auth,
        )["hostids"][0]
        print("Создан хост '%s': %s" % (ZBX_HOSTNAME, hostid))

    # Триггер «свободно места < 25%»
    try:
        expr = TRIGGER_EXPRESSION_TEMPLATE.format(host=ZBX_HOSTNAME)
        triggers = api_request(
            "trigger.get",
            {
                "output": ["triggerid"],
                "hostids": hostid,
                "search": {"description": "Диск: свободно меньше 25%"},
                "searchByAny": False,
            },
            auth,
        )
        if triggers:
            print("Триггер «свободно меньше 25%» уже существует.")
        else:
            api_request(
                "trigger.create",
                {
                    "description": TRIGGER_DESCRIPTION,
                    "expression": expr,
                    "priority": TRIGGER_PRIORITY,
                },
                auth,
            )
            print("Создан триггер: %s" % TRIGGER_DESCRIPTION)
    except RuntimeError as e:
        print("Триггер по диску не создан (можно добавить вручную): %s" % e)

    # Элементы для виджетов дашборда. Agent 2 не поддерживает system.run — используем UserParameter (98_docker_commands.conf).
    ifaces = api_request("hostinterface.get", {"hostids": hostid, "output": ["interfaceid"]}, auth)
    interfaceid = int(ifaces[0]["interfaceid"]) if ifaces else None
    dash_items = {}
    # (name, key, value_type, units). Ключи docker.* — из UserParameter в agent2.d (API не позволяет менять ключ, создаём новые)
    items_to_ensure = [
        ("Docker: running containers", "docker.containers.running", 4, None),
        ("Docker: exited containers", "docker.containers.exited", 4, None),
        ("Docker: Swarm state", "docker.swarm.state", 4, None),
        ("Disk: /hostfs free %", "vfs.fs.size[/hostfs,pfree]", 0, "%"),
    ]
    for name, key, value_type, units in items_to_ensure:
        if key in dash_items:
            continue
        existing = api_request("item.get", {"hostids": hostid, "filter": {"key": key}, "output": ["itemid"]}, auth)
        if existing:
            dash_items[key] = int(existing[0]["itemid"])
        elif interfaceid:
            try:
                params = {
                    "hostid": hostid,
                    "name": name,
                    "key": key,
                    "type": 0,
                    "value_type": value_type,
                    "interfaceid": interfaceid,
                    "delay": "60s",
                }
                if units:
                    params["units"] = units
                res = api_request("item.create", params, auth)
                dash_items[key] = int(res["itemids"][0])
                print("Создан элемент: %s" % name)
            except RuntimeError as e:
                print("Элемент «%s» не создан: %s" % (name, e))

    # Дашборд «Главный экран»
    dashboard_name = "Главный экран"
    gid = int(groupid)
    me = api_request("user.get", {"output": ["userid"], "filter": {"username": ZABBIX_USER}}, auth)
    userid = int(me[0]["userid"]) if me else 1

    def make_widgets():
        w = []
        # Ряд 0: Проблемы по важности, Запущенные контейнеры, Exited контейнеры
        w.append({
            "type": "problemsbysv",
            "name": "Проблемы по важности",
            "x": 0, "y": 0, "width": 24, "height": 5, "view_mode": 0,
            "fields": [{"type": 2, "name": "groupids.0", "value": gid}, {"type": 1, "name": "reference", "value": "SEV01"}],
        })
        item_running = dash_items.get(items_to_ensure[0][1])
        if item_running:
            w.append({
                "type": "item",
                "name": "Запущенные контейнеры (docker ps)",
                "x": 24, "y": 0, "width": 24, "height": 8, "view_mode": 0,
                "fields": [{"type": 4, "name": "itemid.0", "value": str(item_running)}, {"type": 0, "name": "show.0", "value": 1}, {"type": 0, "name": "show.1", "value": 2}],
            })
        item_exited = dash_items.get(items_to_ensure[1][1])
        if item_exited:
            w.append({
                "type": "item",
                "name": "Exited контейнеры",
                "x": 48, "y": 0, "width": 24, "height": 8, "view_mode": 0,
                "fields": [{"type": 4, "name": "itemid.0", "value": str(item_exited)}, {"type": 0, "name": "show.0", "value": 1}, {"type": 0, "name": "show.1", "value": 2}],
            })
        # Ряд 1: Проблемы и предупреждения
        w.append({
            "type": "problems",
            "name": "Проблемы и предупреждения",
            "x": 0, "y": 8, "width": 72, "height": 20, "view_mode": 0,
            "fields": [
                {"type": 2, "name": "groupids.0", "value": gid},
                {"type": 0, "name": "show", "value": 3},
                {"type": 0, "name": "show_lines", "value": 25},
                {"type": 0, "name": "show_timeline", "value": 1},
                {"type": 0, "name": "show_opdata", "value": 1},
                {"type": 1, "name": "reference", "value": "PRB01"},
            ],
        })
        # Ряд 2: Диск, Swarm
        item_disk = dash_items.get(items_to_ensure[3][1])
        if item_disk:
            w.append({
                "type": "gauge",
                "name": "Свободно места на диске (%)",
                "x": 0, "y": 28, "width": 24, "height": 10, "view_mode": 0,
                "fields": [
                    {"type": 4, "name": "itemid.0", "value": str(item_disk)},
                    {"type": 1, "name": "min", "value": "0"},
                    {"type": 1, "name": "max", "value": "100"},
                    {"type": 0, "name": "show.0", "value": 1}, {"type": 0, "name": "show.1", "value": 2}, {"type": 0, "name": "show.2", "value": 4}, {"type": 0, "name": "show.3", "value": 5},
                ],
            })
        item_swarm = dash_items.get(items_to_ensure[2][1])
        if item_swarm:
            w.append({
                "type": "item",
                "name": "Состояние Docker Swarm",
                "x": 24, "y": 28, "width": 24, "height": 10, "view_mode": 0,
                "fields": [{"type": 4, "name": "itemid.0", "value": str(item_swarm)}, {"type": 0, "name": "show.0", "value": 1}, {"type": 0, "name": "show.1", "value": 2}],
            })
        return w

    existing_dash = api_request(
        "dashboard.get",
        {"filter": {"name": dashboard_name}, "output": ["dashboardid"], "selectPages": "extend"},
        auth,
    )
    if existing_dash:
        dash_id = existing_dash[0]["dashboardid"]
        pages = existing_dash[0].get("pages", [])
        if pages:
            page = pages[0]
            existing_names = {w.get("name") for w in page.get("widgets", []) if w.get("name")}
            new_widgets = make_widgets()
            to_add = [nw for nw in new_widgets if nw["name"] not in existing_names]
            max_bottom = max((int(w.get("y", 0)) + int(w.get("height", 4)) for w in page.get("widgets", [])), default=0)
            pos_by_name = {
                "Запущенные контейнеры (docker ps)": (0, max_bottom, 24, 8),
                "Exited контейнеры": (24, max_bottom, 24, 8),
                "Свободно места на диске (%)": (48, max_bottom, 24, 10),
                "Состояние Docker Swarm": (0, max_bottom + 10, 24, 10),
            }
            name_to_key = {
                "Запущенные контейнеры (docker ps)": items_to_ensure[0][1],
                "Exited контейнеры": items_to_ensure[1][1],
                "Свободно места на диске (%)": items_to_ensure[3][1],
                "Состояние Docker Swarm": items_to_ensure[2][1],
            }
            clean_widgets = []
            for w in page.get("widgets", []):
                clean = {"type": w["type"], "name": w.get("name", ""), "x": w.get("x", 0), "y": w.get("y", 0), "width": w.get("width", 6), "height": w.get("height", 4), "view_mode": w.get("view_mode", 0)}
                if w.get("widgetid"):
                    clean["widgetid"] = w["widgetid"]
                if w.get("fields") is not None:
                    fields = list(w["fields"])
                    item_key = name_to_key.get(w.get("name"))
                    if item_key and item_key in dash_items:
                        for i, f in enumerate(fields):
                            if isinstance(f, dict) and f.get("name") == "itemid.0":
                                fields[i] = {"type": 4, "name": "itemid.0", "value": str(dash_items[item_key])}
                                break
                    clean["fields"] = fields
                clean_widgets.append(clean)
            for nw in to_add:
                xywh = pos_by_name.get(nw["name"], (0, max_bottom, 24, 8))
                nw["x"], nw["y"], nw["width"], nw["height"] = xywh
                clean_widgets.append(nw)
            api_request("dashboard.update", {"dashboardid": dash_id, "pages": [{"dashboard_pageid": page["dashboard_pageid"], "widgets": clean_widgets}]}, auth)
            if to_add:
                print("В дашборд «%s» добавлены виджеты: %s." % (dashboard_name, ", ".join(w["name"] for w in to_add)))
            else:
                print("Дашборд «%s» обновлён (привязка к элементам исправлена)." % dashboard_name)
        else:
            print("Дашборд «%s» уже существует." % dashboard_name)
    else:
        widgets = make_widgets()
        api_request(
            "dashboard.create",
            {
                "name": dashboard_name,
                "display_period": 60,
                "auto_start": 1,
                "pages": [{"name": "", "widgets": widgets}],
                "users": [{"userid": userid, "permission": 3}],
                "userGroups": [],
            },
            auth,
        )
        print("Создан дашборд «%s» с виджетами: проблемы, контейнеры, диск, Swarm." % dashboard_name)

    print("Готово. Проверьте хост, Latest data и дашборд «Главный экран» в веб-интерфейсе.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print("Ошибка: %s" % e, file=sys.stderr)
        sys.exit(1)
