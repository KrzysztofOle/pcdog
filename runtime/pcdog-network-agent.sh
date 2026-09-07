#!/usr/bin/env bash
# Privileged, narrowly-scoped Wi-Fi agent. It has no GPIO or power operations.
set -eu
export PYTHONPATH='/opt/pcdog/lib'
exec /usr/bin/python3 -m pcdog_runtime.network_agent --socket /run/pcdog-network-agent/agent.sock
