#!/bin/zsh
# Build dist/LiveReact.app (unsigned, ad-hoc signed by PyInstaller) and zip it.
#   packaging/macos/build_app.sh [ZIP_PATH]     default: dist/LiveReact-macos-arm64.zip
# PYTHON=/path/to/python3.13 overrides the interpreter. Built and tested with the
# uv-managed CPython 3.13.16 (aarch64, ships a shared libpython3.13.dylib).
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO="$PWD"

PYTHON="${PYTHON:-$HOME/.local/bin/python3.13}"
VENV="$REPO/.build-venv"
ZIP="${1:-$REPO/dist/LiveReact-macos-arm64.zip}"

if [ "$(uname -m)" != "arm64" ]; then
  echo "This spec targets arm64; run it on an Apple Silicon Mac." >&2
  exit 1
fi
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version' \
  || { echo "Need Python 3.13 (set PYTHON=...)" >&2; exit 1; }

echo "==> Clean build venv: $VENV ($("$PYTHON" --version))"
rm -rf "$VENV"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet "${REPO}[ui,hardware]" "pyinstaller>=6.10"

echo "==> PyInstaller"
rm -rf "$REPO/build/pyinstaller" "$REPO/dist/LiveReact" "$REPO/dist/LiveReact.app"
"$VENV/bin/pyinstaller" --noconfirm --clean \
  --distpath "$REPO/dist" --workpath "$REPO/build/pyinstaller" \
  "$REPO/packaging/macos/LiveReact.spec"
# The onedir COLLECT folder is an intermediate; the .app is the product.
rm -rf "$REPO/dist/LiveReact"

echo "==> Zip: $ZIP"
mkdir -p "$(dirname "$ZIP")"
rm -f "$ZIP"
ditto -c -k --keepParent "$REPO/dist/LiveReact.app" "$ZIP"

echo "==> Done"
du -sh "$REPO/dist/LiveReact.app" "$ZIP"
