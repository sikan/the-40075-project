#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")/.."
exec /usr/bin/python3 scripts/tracker.py refresh
