# AutoImportClips2DR

Ein Automatisierungstool für DaVinci Resolve, um SD-Karten-Backups, Dateisortierung und Proxy-Erstellung mit NVIDIA-Beschleunigung effizient abzuwickeln.

---

## 🚀 Funktionen
* **Automatisierte Ordnerstruktur**: Sortierung nach Datum, Wochentag oder Projekttagen.
* **Intelligentes Proxy-Handling**: Nutzt NVIDIA NVENC für extrem schnelles Proxy-Rendering (H.265/H.264).
* **DaVinci Resolve Integration**: Importiert Clips direkt in die korrekten Media-Pool-Bins.
* **Pancake-Timelines**: Legt synchron zu den Footage-Bins auch Pancake-Timelines für jede Kamera an
* **Kamera-Erkennung**: Erkennt den Kameratyp anhand des Labels der SD-Karte und setzt die Meta-Daten entsprechend für weitere Verarbeitungen.
* Befüllt optional die Pancake-Timelines mit allen Clips in chronologischer Reihenfolge
* Setzt optional den Color Space Kamera-spezifisch (für "DaVinci YRGB Color Managed")


---

## Bemerkung
* Derzeit funktioniert das Setzen des "Input Gamma" per API nicht korrekt. Daher muss das nach wie vor manuell gesetzt werden

--- 

## 🛠 Voraussetzungen
* **DaVinci Resolve** (Studio)
* **FFmpeg**: Muss im System-PATH installiert sein.
    * *Prüfung*: Gib in der CMD `ffmpeg -version` ein.
* **Python 3.x**: Muss auf dem System vorhanden sein.

---

## ⚙️ Installation & Einrichtung

### 1. Repository-Vorbereitung
Lade das Repository in ein Verzeichnis deiner Wahl, z. B.:
`C:\Users\jochen\Documents\GitHub\AutoImportClips2DR\Scripts`

### 2. Integration in DaVinci Resolve
Damit das Skript im Menü **Workspace > Scripts** erscheint, muss `Start_Ingest.py` an den von DaVinci Resolve vorgesehenen Ort kopiert werden:

1. Kopiere die Datei `Start_Ingest.py` in den Ordner:
   `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Edit`
2. Öffne die kopierte `Start_Ingest.py` in einem Editor.
3. Passe die Variable `ScriptPath` exakt an den Pfad an, in dem du die restlichen Skript-Dateien (`main_gui.py`, `ingest_worker.py`, `config.json`) gespeichert hast:
   ```python
   ScriptPath = r"C:\Users\DEIN_USER\Documents\GitHub\AutoImportClips2DR\Scripts"
   
### 3. Konfiguration der Pfade

Um das Skript flexibel zu halten, werden die Pfade in einer externen Datei definiert.

1. Öffne die Datei config.json in deinem Skript-Ordner.
2. Passe die Pfade zu deinen Medien-, Ziel- und Proxy-Verzeichnissen an:Passe die Datei config.json in deinem Skript-Ordner an deine lokale Struktur an:

```json
JSON{
    "ALL_MEDIA_DIR": "D:\\Videos",
    "BASE_TARGET_DIR": "D:\\Videos\\01-Productions",
    "BASE_PROXY_DIR": "D:\\Videos\\04-DR-Folders\\ProxyMedia"
}
```

### 📂 Struktur

| Datei | Beschreibung |
| :--- | :--- |
| main_gui.py | Hauptoberfläche (Tkinter) und GUI-Logik. |
| ingest_worker.py | Logik für Kopier- und Render-Prozesse. | 
| Start_Ingest.py | Einstiegspunkt für Resolve (muss im Script-Ordner liegen). | 
| config.json | Benutzerspezifische Pfadkonfiguration. | 

### 💡 Tipps
* **Smart-Bins**: Durch das Erstellen von kameraspezifischen Smart-Bins können weitere Anpassungen schnell vorgenommen werden.
* **.gitignore**: Achte darauf, eine .gitignore Datei anzulegen, um config.json (wegen privater Pfade) oder Log-Dateien nicht versehentlich mit hochzuladen.
* **Fehlersuche**: Sollte das Skript nicht starten, prüfe die Datei script_error_log.txt auf deinem Desktop.

### Offene ToDos
* Automatisches Setzen des "Input Gamma", sobald das mit der API geht.
* Verschieben der Kameratypen in die json-Datei - auch für flexible Erweiterbarkeit.