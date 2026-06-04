#!/usr/bin/env python
import os
import sys

# API-Pfad für Windows bereitstellen
RESOLVE_SCRIPT_API = r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"
if os.path.exists(RESOLVE_SCRIPT_API) and RESOLVE_SCRIPT_API not in sys.path:
    sys.path.append(RESOLVE_SCRIPT_API)

# Pfade und Verzeichnisse
ALL_MEDIA_DIR = r""
BASE_TARGET_DIR = r""
BASE_PROXY_DIR = r""

# Dateiendungen und System-Konstanten
VALID_EXTENSIONS = ('.mov', '.mp4', '.mxf', '.braw', '.wav', '.mp3', '.jpg', '.jpeg', '.png', '.arw', '.cr3', '.rw2')
PROXY_ELIGIBLE_EXTENSIONS = ('.mov', '.mp4', '.mxf', '.braw')
DRIVE_REMOVABLE = 2

WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]