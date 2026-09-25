#!/usr/bin/env bash
set -euo pipefail
exec 3<>/dev/tcp/127.0.0.1/9000
printf 'GET /health/ready HTTP/1.0\r\n\r\n' >&3
read -r status <&3
[[ "$status" == *" 200 "* ]]
