#!/bin/sh
set -eu
exec python "${GC_PACK_DIR:?GC_PACK_DIR must be set}/assets/brief.py" "$@"
