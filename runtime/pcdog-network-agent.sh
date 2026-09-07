#!/usr/bin/env bash
# Privileged, narrowly-scoped Wi-Fi agent. It has no GPIO or power operations.
set -eu
export PYTHONPATH='/opt/pcdog/lib'
exec /usr/bin/python3 -c 'from pcdog_runtime.network_agent import main; main()' --socket /run/pcdog-network-agent/agent.sock
