#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Настройка Zabbix через API: группа, хост с агентом, шаблоны Linux/Docker, триггер «свободно места < 25%».
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
    if auth:
        body["auth"] = auth
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=REQUEST_HEADERS,
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
    gr = api_request("hostgroup.get", {"filter": {"name": ZABBIX_HOST_GROUP}, "output": ["groupid"]})
    if gr:
        groupid = gr[0]["groupid"]
        print("Группа '%s' уже есть: %s" % (ZABBIX_HOST_GROUP, groupid))
    else:
        groupid = api_request("hostgroup.create", {"name": ZABBIX_HOST_GROUP})["groupids"][0]
        print("Создана группа '%s': %s" % (ZABBIX_HOST_GROUP, groupid))

    # Шаблоны
    tpl = api_request(
        "template.get",
        {
            "output": ["templateid", "name"],
            "search": {"name": [ZABBIX_TEMPLATE_LINUX, ZABBIX_TEMPLATE_DOCKER]},
            "searchByAny": True,
        },
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
    existing = api_request("host.get", {"filter": {"host": ZBX_HOSTNAME}, "output": ["hostid"]})
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
        )["hostids"][0]
        print("Создан хост '%s': %s" % (ZBX_HOSTNAME, hostid))

    # Триггер «свободно места < 25%»
    expr = TRIGGER_EXPRESSION_TEMPLATE.format(host=ZBX_HOSTNAME)
    triggers = api_request(
        "trigger.get",
        {
            "output": ["triggerid"],
            "hostids": hostid,
            "search": {"description": "Диск: свободно меньше 25%"},
            "searchByAny": False,
        },
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
        )
        print("Создан триггер: %s" % TRIGGER_DESCRIPTION)

    print("Готово. Проверьте хост и Latest data в веб-интерфейсе.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print("Ошибка: %s" % e, file=sys.stderr)
        sys.exit(1)
