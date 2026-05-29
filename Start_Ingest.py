import sys
import os

# Dieses Script muss in den Pfad von Davinci Resolve, also z.B.:
# C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Edit

ScriptPath = r"C:\Users\joche\Documents\GitHub\AutoImportClips2DR\Scripts"

try:
    sys.path.append(ScriptPath)
    
    # 1. Modul importieren (muss main_gui heißen, wenn das File so heißt)
    import main_gui
    
    # Optional: Erzwingen, dass das Modul neu geladen wird (gut für Tests)
    import importlib
    importlib.reload(main_gui)
    
    # 2. Die Klasse aufrufen (Namen anpassen, falls deine Klasse anders heißt)
    # Beispiel: Wenn deine GUI-Klasse in main_gui.py 'ResolveIngestGUI' heißt:
    import tkinter as tk
    root = tk.Tk()
    app = main_gui.ResolveIngestGUI(root)
    root.mainloop()
    
except Exception as e:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Start-Fehler", f"Fehler beim Starten:\n{e}")
    root.destroy()