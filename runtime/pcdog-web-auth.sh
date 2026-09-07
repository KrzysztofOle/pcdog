#!/usr/bin/env bash
# Ustawia lokalne hasło Web Panelu bez umieszczania go w repozytorium.

set -eu

export PYTHONPATH='/opt/pcdog/lib'
exec /usr/bin/python3 -m pcdog_runtime.web_auth_setup "$@"
