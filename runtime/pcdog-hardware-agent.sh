#!/usr/bin/env bash
# Dedicated GPIO agent. GPIO19/GPIO20 are always read-only; GPIO17/GPIO18 output commands
# remain disabled unless root supplied a confirmed control polarity.
set -eu
export PYTHONPATH='/opt/pcdog/lib'
readonly HARDWARE_AGENT_SOCKET='/run/pcdog-hardware-agent/agent.sock'

case "${PCDOG_CONTROL_POLARITY:-}" in
  '')
    exec /usr/bin/python3 -m pcdog_runtime.hardware_agent --socket "$HARDWARE_AGENT_SOCKET"
    ;;
  active-high|active-low)
    exec /usr/bin/python3 -m pcdog_runtime.hardware_agent --socket "$HARDWARE_AGENT_SOCKET" --control-polarity "$PCDOG_CONTROL_POLARITY"
    ;;
  *)
    echo 'Nieprawidłowe PCDOG_CONTROL_POLARITY; sterowanie GPIO nie zostanie uruchomione.' >&2
    exit 64
    ;;
esac
