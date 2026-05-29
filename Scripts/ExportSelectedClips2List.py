import os

def export_clips_to_local_list():
    # Verbindung zu Resolve herstellen
    resolve = bmd.scriptapp("Resolve")
    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject()
    media_pool = project.GetMediaPool()
    
    # Ausgewählte Clips holen
    selected_clips = media_pool.GetSelectedClips()
    
    if not selected_clips:
        print("Fehler: Keine Clips im Media Pool ausgewählt!")
        return

    # Dictionary, um Pfade nach Verzeichnissen zu gruppieren
    directories = {}

    for clip in selected_clips:
        file_path = clip.GetClipProperty("File Path")
        if file_path:
            folder = os.path.dirname(file_path)
            if folder not in directories:
                directories[folder] = []
            directories[folder].append(file_path)

    # Für jedes Verzeichnis eine eigene Liste schreiben
    for folder, file_list in directories.items():
        list_path = os.path.join(folder, "gyro_list.txt")
        try:
            with open(list_path, "w", encoding="utf-8") as f:
                for path in file_list:
                    f.write(path + "\n")
            print(f"Liste erstellt in: {folder}")
        except Exception as e:
            print(f"Fehler beim Schreiben in {folder}: {e}")

    print(f"Abgeschlossen: {len(directories)} Listen wurden aktualisiert.")

if __name__ == "__main__":
    export_clips_to_local_list()