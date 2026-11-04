#!/bin/sh
set -eu
exec python3 "${GC_PACK_DIR}/assets/delivery.py" "$@"
