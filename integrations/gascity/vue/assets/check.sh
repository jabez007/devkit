#!/bin/sh
set -eu
GC_BIN=$(command -v gc) || exit 75
command -v python3 >/dev/null || exit 75
export GC_BIN
exec python3 "$(dirname "$0")/delivery.py" check
