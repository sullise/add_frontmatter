#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
MODE="${1:-run}"
APP_NAME="Add-Frontmatter-Title-Test"
BUILD_PYTHON="${AF_BUILD_PYTHON:-$ROOT_DIR/../work/mac-build-venv/bin/python}"
if [[ ! -x "$BUILD_PYTHON" ]]; then
  echo "Set AF_BUILD_PYTHON to a Python environment with this package, PyInstaller, and Tk installed." >&2
  exit 1
fi
case "$MODE" in
  run|--verify|--build-only) ;;
  *) echo "usage: $0 [run|--verify|--build-only]" >&2; exit 2 ;;
esac
pkill -x "$APP_NAME" >/dev/null 2>&1 || true
FFMPEG_PATH="$($BUILD_PYTHON -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')"
"$BUILD_PYTHON" -m PyInstaller --noconfirm --clean --onedir --windowed \
  --name "$APP_NAME" --paths src \
  --add-binary "$FFMPEG_PATH:." \
  --add-data "src/add_frontmatter/assets:add_frontmatter/assets" \
  --icon src/add_frontmatter/assets/sps_logo.icns \
  --collect-data tzdata \
  --osx-bundle-identifier com.sullise.add-frontmatter.title-test \
  src/run_add_frontmatter_gui.py
APP_BUNDLE="$ROOT_DIR/dist/$APP_NAME.app"
if [[ "$MODE" != --build-only ]]; then
  /usr/bin/open -n "$APP_BUNDLE"
fi
if [[ "$MODE" == --verify ]]; then
  sleep 2
  pgrep -x "$APP_NAME" >/dev/null
fi
