import sys
import os

# Dieses Script muss in den Pfad von Davinci Resolve, also z.B.:
# C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Edit

ScriptPath = r"C:\Users\joche\Documents\GitHub\AutoImportClips2DR\Scripts"

sys.path.append(ScriptPath)

# 1. Modul importieren (muss main_ColMgmt heißen, wenn das File so heißt)
import main_ColMgmt

# Optional: Erzwingen, dass das Modul neu geladen wird (gut für Tests)
import importlib
importlib.reload(main_ColMgmt)

main_ColMgmt.automate_color_management_by_bin()
