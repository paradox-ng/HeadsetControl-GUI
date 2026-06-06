#!/usr/bin/env bash
# Launch the HeadsetControl tray app from the project directory.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
exec python -m headsetcontrol_gui "$@"
