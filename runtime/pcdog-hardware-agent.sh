#!/usr/bin/env bash
# Dedicated read-only GPIO agent: only GPIO19 and GPIO20 are readable.
set -eu
export PYTHONPATH='/opt/pcdog/lib'
exec /usr/bin/python3 -m pcdog_runtime.hardware_agent --socket /run/pcdog-hardware-agent/agent.sock
