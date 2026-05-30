#!/usr/bin/env python
import os
import sys
import json

def load_config():
    """Sucht und lädt die config.json im selben Verzeichnis wie das Skript."""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

# Konfiguration global laden
CONFIG = load_config()

def set_color_space_from_config(clip, clip_name, camera_type):
    """Weist den Input Color Space basierend auf den Mappings in der config.json zu."""
    if not camera_type:
        return False
        
    camera_type_upper = camera_type.upper()
    mappings = CONFIG.get("camera_mappings", [])
    
    # Durchsuche die Mappings aus der JSON
    for mapping in mappings:
        # Extrahiere die Suchbegriffe aus der JSON und setze sie auf Großbuchstaben
        keywords = [kw.upper() for kw in mapping.get("search_keywords", [])]
        mapping_type = mapping.get("camera_type", "").upper()
        
        # MATCH-LOGIK: 
        # Fall 1: Der Metadaten-Kameratyp (z.B. "S5II") ist direkt in den Such-Keywords enthalten
        # Fall 2: Der Metadaten-Kameratyp entspricht exakt dem konfigurierten camera_type
        if camera_type_upper in keywords or camera_type_upper == mapping_type:
            color_space = mapping.get("input_color_space")
            
            if not color_space:
                return False
                
            # Wenn der Farbraum auf Standard/Rec.709 bleiben soll, überspringen wir die Zuweisung
            if "Rec.709" in color_space or "Baseline" in color_space:
                print(f"  -> [Standard] {clip_name} bleibt auf Standard-Projektfarbraum (Metadaten: '{camera_type}').")
                return True
                
            # Setze den konfigurierten Farbraum in DaVinci Resolve
            if clip.SetClipProperty("Input Color Space", color_space):
                print(f"  -> [Erfolg] {clip_name} -> '{color_space}' zugewiesen (Metadaten: '{camera_type}').")
                
                # Optionale Absicherung für ältere Lumix-Workflows (schadet nicht, falls es fehlschlägt)
                if "LUMIX" in mapping_type or "S5" in camera_type_upper:
                    clip.SetClipProperty("Input Gamma", "Panasonic V-Log")
                    
                return True
            else:
                print(f"  -> [FEHLER] Resolve API verweigerte '{color_space}' für {clip_name}.")
                return False
                
    print(f"  -> [HINWEIS] Kein Farbraum-Mapping für Kameratyp '{camera_type}' in config.json gefunden.")
    return False

def process_bin(folder):
    """Durchsucht rekursiv alle Bins und taggt die Clips anhand ihrer echten Metadaten."""
    clips = folder.GetClipList()
    current_bin_name = folder.GetName()
    
    print(f"[Prüfe Ordner] {current_bin_name}")
    
    for clip in clips:
        if not clip:
            continue
            
        clip_name = clip.GetName()
        
        # Holt den Kameratyp direkt aus dem Metadatenfeld "Camera Type"
        meta_camera_type = clip.GetMetadata("Camera Type")
        
        if meta_camera_type:
            set_color_space_from_config(clip, clip_name, meta_camera_type)
        elif clip.GetClipProperty("Type") != "Timeline":
            # Keine Metadaten vorhanden (z.B. Audio/Grafiken)
            pass

    # Rekursiver Durchlauf für alle Unterordner
    sub_folders = folder.GetSubFolderList()
    for sub_folder in sub_folders:
        process_bin(sub_folder)

def automate_color_management_by_bin():
    import DaVinciResolveScript as dvr_script
    
    if "resolve" in globals():
        resolve_app = globals()["resolve"]
    else:
        resolve_app = dvr_script.scriptapp("Resolve")
        
    if not resolve_app:
        print("[FEHLER] Verbindung zu DaVinci Resolve fehlgeschlagen.")
        return

    project_manager = resolve_app.GetProjectManager()
    current_project = project_manager.GetCurrentProject()
    
    if not current_project:
        print("[FEHLER] Kein aktives Projekt geöffnet.")
        return
        
    media_pool = current_project.GetMediaPool()
    root_folder = media_pool.GetRootFolder()
    
    print("\n--- Starte automatisches Farbmanagement via JSON-Konfiguration ---")
    process_bin(root_folder)
    
    # Projekt speichern, um UI-Refresh in Resolve zu erzwingen
    project_manager.SaveProject()
    print("--- Fertig und Projekt gespeichert! ---\n")

if __name__ == "__main__":
    automate_color_management_by_bin()