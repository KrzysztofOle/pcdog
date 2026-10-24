#!/usr/bin/env bash
# Install or roll back only the read-only PcDog CLI.
set -eu
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec /usr/bin/python3 "$script_dir/install-cli.py" "$@"
