#!/usr/bin/env bash
# Build a self-contained AppImage of HeadsetControl GUI for the host's
# architecture. Works locally and in CI. Produces
# dist/HeadsetControl-GUI-<arch>.AppImage (x86_64 or aarch64).
set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"

# Map the host machine to AppImage/appimagetool arch names.
case "$(uname -m)" in
  x86_64)        AIARCH=x86_64 ;;
  aarch64|arm64) AIARCH=aarch64 ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

APP="headsetcontrol-gui"
BUILD="$ROOT/build"
DIST="$ROOT/dist"
APPDIR="$BUILD/AppDir"
OUTPUT="$DIST/HeadsetControl-GUI-${AIARCH}.AppImage"

rm -rf "$BUILD" "$DIST"
mkdir -p "$APPDIR" "$DIST"

# 1. Bundle the app + Python + Qt with PyInstaller (onedir).
python -m pip install --upgrade pip pyinstaller PySide6
python -m PyInstaller \
  --name "$APP" \
  --windowed \
  --noconfirm \
  --clean \
  --paths "$ROOT" \
  --distpath "$BUILD/pyinstaller" \
  --workpath "$BUILD/pyi-work" \
  --specpath "$BUILD" \
  "$HERE/launcher.py"

# 2. Lay out the AppDir.
mkdir -p "$APPDIR/usr/bin"
cp -r "$BUILD/pyinstaller/$APP/." "$APPDIR/usr/bin/"

install -Dm644 "$HERE/$APP.desktop" "$APPDIR/usr/share/applications/$APP.desktop"
install -Dm644 "$HERE/$APP.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/$APP.svg"
cp "$HERE/$APP.desktop" "$APPDIR/$APP.desktop"
cp "$HERE/$APP.svg" "$APPDIR/$APP.svg"
ln -sf "$APP.svg" "$APPDIR/.DirIcon"

install -m755 "$HERE/AppRun" "$APPDIR/AppRun"

# 3. Pack it with appimagetool (no FUSE needed via extract-and-run).
TOOL="$BUILD/appimagetool.AppImage"
curl -fsSL -o "$TOOL" \
  "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${AIARCH}.AppImage"
chmod +x "$TOOL"

ARCH="$AIARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUTPUT"

echo "Built: $OUTPUT"
