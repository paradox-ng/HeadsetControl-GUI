#!/usr/bin/env bash
# Build a self-contained AppImage of HeadsetControl GUI.
# Works locally and in CI. Produces dist/HeadsetControl-GUI-x86_64.AppImage.
set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"

APP="headsetcontrol-gui"
BUILD="$ROOT/build"
DIST="$ROOT/dist"
APPDIR="$BUILD/AppDir"

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
  "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
chmod +x "$TOOL"

ARCH=x86_64 "$TOOL" --appimage-extract-and-run \
  "$APPDIR" "$DIST/HeadsetControl-GUI-x86_64.AppImage"

echo "Built: $DIST/HeadsetControl-GUI-x86_64.AppImage"
