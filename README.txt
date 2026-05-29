AutoImportClips2DR
Dieses Projekt automatisiert den Import von Videoclips in DaVinci Resolve, inklusive einer Batch-Verarbeitung und Proxy-Verknüpfung mittels FFmpeg.

Voraussetzungen
DaVinci Resolve (getestet mit der aktuellen Version).

FFmpeg: Muss installiert und in der Windows-System-PATH-Variable hinterlegt sein, damit das Skript die Videodateien konvertieren kann.
(Test: Öffne CMD und gib ffmpeg -version ein. Wenn eine Versionsinfo erscheint, ist alles bereit.)

Installation & Einrichtung
1. Repository-Pfad
Stelle sicher, dass der Ordner, in den du dieses Repository geklont hast, mit dem Pfad in der Start_Ingest.py übereinstimmt:
C:\Users\joche\Documents\GitHub\AutoImportClips2DR\Scripts
(Falls du einen anderen Speicherort bevorzugst, musst du die Variable ScriptPath in der Start_Ingest.py entsprechend anpassen.)

2. Skript-Integration in DaVinci Resolve
Damit DaVinci Resolve das Skript im Menü unter Workspace > Scripts anzeigt, muss eine Verknüpfung (oder die Datei selbst) an folgenden Ort kopiert werden:

Zielordner:
C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Edit

Kopiere die Datei Start_Ingest.py in diesen Ordner. DaVinci Resolve sucht beim Start (oder beim Öffnen des Scripting-Menüs) in diesem Verzeichnis nach ausführbaren Python-Dateien.

Struktur der Dateien
/Scripts/main_gui.py: Enthält die GUI-Klasse (ResolveIngestGUI) und die Kernlogik.

Start_Ingest.py: Der Einstiegspunkt für Resolve, der den Pfad zum Modul konfiguriert und die GUI instanziiert.

Hinweis zur Konfiguration
Die Pfade für Medien und Zielverzeichnisse sind aktuell hart kodiert in main_gui.py (oder der entsprechenden Hauptdatei) unter dem Abschnitt KONFIGURATION. Passe diese Variablen (ALL_MEDIA_DIR, BASE_TARGET_DIR, etc.) an deine lokale Ordnerstruktur an, bevor du das Skript das erste Mal ausführst.

Ein paar Tipps für die Dokumentation im Git:
.gitignore Datei: Falls noch nicht vorhanden, erstelle eine .gitignore, damit keine temporären Dateien oder Log-Dateien (wie deine debug.txt oder script_error_log.txt) mit ins Repository geladen werden.

Pfad-Variablen: Da du in deinem Code absolute Pfade wie D:\Benutzer\Jochen\... verwendest, könnte es sinnvoll sein, diese in einer kleinen config.json auszulagern. Wenn du das Skript mal auf einem anderen Rechner nutzen willst, musst du dann nicht den Quellcode ändern.