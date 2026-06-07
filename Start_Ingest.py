import sys
import os
import json

# Dieses Script muss in den Pfad von Davinci Resolve, also z.B.:
# C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Comp 

# Ermittelt das Verzeichnis, in dem DIESES Skript (Start_Ingest.py) liegt
# Robuster Schutz, da DaVinci Resolve bei interner Skript-Ausführung kein __file__ bereitstellt
try:
    THIS_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Fallback 1: Prüfen, ob Resolve den Pfad eventuell via Argumente übergibt
    if len(sys.argv) > 0 and sys.argv[0] and os.path.exists(sys.argv[0]):
        THIS_SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
    else:
        # Fallback 2: Fixer Windows-Standardpfad für Resolve Fusion Scripts
        THIS_SCRIPT_DIR = r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Comp"
        
def load_and_validate_config(script_dir):
    config_path = os.path.join(script_dir, 'config.json')
    
    # 1. Kontrolle: Existiert die config.json überhaupt?
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Die Konfigurationsdatei wurde nicht gefunden:\n{config_path}")
        
    with open(config_path, 'r', encoding='utf-8') as f:
        try:
            config = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Die config.json enthält ungültiges JSON-Format:\n{e}")
            
    # 2. Kontrolle: Ist die Basis-Variable ALL_MEDIA_DIR vorhanden?
    root_dir = config.get("ALL_MEDIA_DIR")
    if not root_dir:
        raise KeyError("Der erforderliche Schlüssel 'ALL_MEDIA_DIR' fehlt in der config.json.")
        
    # Normalisieren des Hauptpfads
    root_dir = os.path.abspath(os.path.expanduser(root_dir))
    config["ALL_MEDIA_DIR"] = root_dir
    
    # 3. Pfade auflösen (relativ zu ALL_MEDIA_DIR, falls sie nicht absolut sind)
    path_keys = ["BASE_TARGET_DIR", "BASE_PROXY_DIR", "BASE_DRX_DIR"]
    for key in path_keys:
        if key not in config or not config[key]:
            raise KeyError(f"Der erforderliche Pfad-Schlüssel '{key}' fehlt oder ist leer in der config.json.")
            
        if not os.path.isabs(config[key]):
            config[key] = os.path.join(root_dir, config[key])
        else:
            config[key] = os.path.abspath(os.path.expanduser(config[key]))

    # 4. Kontrolle: Existieren die Pfade physisch auf dem System?
    # Wir prüfen ALL_MEDIA_DIR sowie die drei aufgelösten Zielordner
    all_checked_paths = {
        "ALL_MEDIA_DIR": config["ALL_MEDIA_DIR"],
        "BASE_TARGET_DIR": config["BASE_TARGET_DIR"],
        "BASE_PROXY_DIR": config["BASE_PROXY_DIR"],
        "BASE_DRX_DIR": config["BASE_DRX_DIR"]
    }
    
    for label, path in all_checked_paths.items():
        if not os.path.exists(path):
            raise NotADirectoryError(
                f"Ungültiger oder nicht erreichbarer Pfad in der Konfiguration!\n\n"
                f"Variable: {label}\n"
                f"Pfad: {path}\n\n"
                f"Bitte prüfen Sie, ob das Laufwerk verbunden oder der Ordner vorhanden ist."
            )
            
    return config

# Pfad zu den restlichen Modulen ermitteln (bevorzugt via Umgebungsvariable, sonst lokal)
ScriptPath = os.getenv("AUTOIMPORTCLIPS2DR_SCRIPT_PATH")
if ScriptPath:
    ScriptPath = os.path.abspath(os.path.expanduser(ScriptPath))
else:
    ScriptPath = THIS_SCRIPT_DIR

try:
    # Konfiguration laden, automatisch zusammensetzen und strikt validieren
    config = load_and_validate_config(THIS_SCRIPT_DIR)
    
    ScriptPath = f"{ScriptPath}\Scripts"
    sys.path.append(ScriptPath)
    
    # 1. Modul importieren
    import main_gui
    
    # Erzwingen, dass das Modul neu geladen wird (gut für Tests)
    import importlib
    importlib.reload(main_gui)
    
    # 2. Die Klasse aufrufen und die geladene/geprüfte config übergeben
    import tkinter as tk
    root = tk.Tk()
    app = main_gui.ResolveIngestGUI(root, config=config)
    root.mainloop()
    
except Exception as e:
    # Fängt alle Validierungsfehler, fehlende Dateien oder Pfad-Defekte ab
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Konfigurations- / Start-Fehler", f"Abbruch wegen Sicherheitsprüfung:\n\n{e}")
    root.destroy()
    sys.exit(1) # Beendet die Ausführung sauber, da Ingest so nicht lauffähig ist