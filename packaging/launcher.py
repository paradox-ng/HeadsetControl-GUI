"""PyInstaller entry point. Kept as a plain script (not a module) because
PyInstaller analyses a script path; it pulls in the headsetcontrol_gui
package via the import below."""

import sys

from headsetcontrol_gui.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
