#!/usr/bin/env bash
# Create esptool-env, the Python venv that huzzah.sh uses, and install the pinned tools from requirements.txt.
#
# Usage:
#   ./setup.sh               Create the venv if needed, then install or update the requirements
#   ./setup.sh --recreate    Delete esptool-env and build it from scratch
#
# PYTHON picks the interpreter, e.g. PYTHON=python3.14 ./setup.sh. Defaults to python3.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/esptool-env"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
PYTHON="${PYTHON:-python3}"

die() {
    echo "error: $*" >&2
    exit 1
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    sed -n '2,/^$/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
    exit 0
fi

command -v "$PYTHON" >/dev/null || die "$PYTHON not found. Install Python 3 or set PYTHON."
[[ -f "$REQUIREMENTS" ]] || die "requirements file not found: $REQUIREMENTS"

if [[ "${1:-}" == "--recreate" ]]; then
    echo "Removing $VENV_DIR"
    rm -rf "$VENV_DIR"
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "Creating $VENV_DIR with $("$PYTHON" --version)"
    "$PYTHON" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$REQUIREMENTS"

echo "Done. Try: ./huzzah.sh port"
