#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install --user --upgrade pip setuptools wheel
python3 -m pip install --user --upgrade buildozer cython virtualenv
export PATH="$HOME/.local/bin:$PATH"
buildozer android debug
