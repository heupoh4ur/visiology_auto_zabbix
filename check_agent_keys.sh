#!/bin/sh
echo "=== docker service ls from agent ==="
docker exec zabbix-agent2 sh -c 'DOCKER_HOST=unix:///var/run/docker.sock docker service ls 2>&1' | head -15
echo "=== docker ps exited from agent ==="
docker exec zabbix-agent2 sh -c 'DOCKER_HOST=unix:///var/run/docker.sock docker ps -a --filter status=exited 2>&1' | head -10
echo "=== zabbix_agent2 -t docker.services.list ==="
docker exec zabbix-agent2 zabbix_agent2 -t docker.services.list 2>&1
echo "=== zabbix_agent2 -t docker.containers.exited.list ==="
docker exec zabbix-agent2 zabbix_agent2 -t docker.containers.exited.list 2>&1
echo "=== zabbix_get from server ==="
docker exec zabbix-server zabbix_get -s 172.17.0.1 -p 10050 -k docker.services.list 2>&1 | head -5
