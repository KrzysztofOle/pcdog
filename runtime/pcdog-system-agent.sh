#!/usr/bin/env bash
# Privileged PcDog system-agent. Stage 3 exposes status only; actions stay disabled.

set -eu

readonly RUNTIME_LIBRARY='/opt/pcdog/lib'
readonly SYSTEM_AGENT_SOCKET='/run/pcdog-system-agent/agent.sock'

export PYTHONPATH="$RUNTIME_LIBRARY"
exec /usr/bin/python3 -m pcdog_runtime.system_agent --socket "$SYSTEM_AGENT_SOCKET"
