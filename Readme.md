# AutoImportClips2DR

Ein Automatisierungstool für DaVinci Resolve Studio, um SD-Karten-Transfer, physikalische Dateisortierung, automatisiertes Metadaten-Tagging, DRX-Grading und Proxy-Erstellung mit NVIDIA-Beschleunigung effizient abzuwickeln.

Die JSON-Datei darf gerne um weitere Kamera-Typen ergänzt werden.

Dieses Readme wurde mit Gemini erstellt und dann manuell angepasst.

---

## 🚀 Funktionen
* **Automatisierte Ordnerstruktur**: Intelligente Sortierung auf der Festplatte nach Datum (`YYMMDD`), Wochentag oder fortlaufenden Projekttagen (`Tag-01`, `Tag-02`, ...).
* **Intelligentes Proxy-Handling**: Nutzt NVIDIA NVENC für extrem schnelles Proxy-Rendering (H.265/H.264) via FFmpeg und verknüpft diese vollautomatisch in DaVinci Resolve.
* **DaVinci Resolve Media Pool Integration**: Importiert Clips direkt in die korrekten Media-Pool-Bins (`Footage`, `Music`, `Images`, `Pancakes`, `Timelines`).
* **Kamera-Erkennung & Tagging**: Erkennt den Kameratyp anhand des Labels der SD-Karte, weist spezifische Resolve-Clipfarben zu und setzt Keyword-Tags.
* **Chronologische Pancake-Timelines**: Erstellt kameraspezifische "Pancake"-Timelines und fügt neue Clips chronologisch sortiert nach Timecode ein.
* **Automatisches DRX-Grading (Resolve 19+)**: Wendet hinterlegte Look-Profile (`.drx`) vollautomatisch über die moderne `NodeGraph`-Schnittstelle auf alle importierten Clips der Timeline an.
* **Generischer Fallback (Rec.709)**: Unbekannte Speicherkarten stürzen nicht ab, sondern werden als generisches `REC709` eingestuft, erhalten eine weiße Clipfarbe und ein definiertes Standard-Mapping.
* **Workflow-optimierte GUI**: Die Standardwerte der Oberfläche sind praxisnah vorbelegt (Pancake-Timelines standardmäßig aktiv, Farbraumzuweisung via Skript inaktiv).
* **Automatischer UI-Wechsel**: Schaltet die Resolve-Oberfläche nach erfolgreichem Ingest sofort auf die **Edit-Page** um, damit der Schnitt direkt starten kann.

---

## ⚠️ Wichtige Bemerkungen
* **Input Gamma Einschränkung**: Da die DaVinci Resolve API in einigen Farbraum-Konfigurationen das Zuweisen des Input Gammas blockiert oder ignoriert, sollte das "Input Gamma" im Media Pool nach dem Import weiterhin manuell überprüft werden.
* **Resolve Studio**: Die Skript-Schnittstelle von DaVinci Resolve ist primär in der **Studio-Version** vollumfänglich freigeschaltet.

--- 

## 🛠 Voraussetzungen
* **DaVinci Resolve Studio** (getestet ab Version 20)
* **FFmpeg**: Muss auf dem System installiert und im System-PATH hinterlegt sein.
    * *Prüfung*: Gib in der Eingabeaufforderung (CMD) `ffmpeg -version` ein.
* **Python 3.x**: Muss im System installiert sein.

---

## 📦 Ordner- und Modulstruktur

Das Projekt ist modular aufgebaut, um maximale Übersicht und Wartbarkeit zu gewährleisten:

```text
AutoImportClips2DR/
│
├── main_gui.py               # Hauptoberfläche (Tkinter) und Thread-Management
├── config.json               # Zentrale Benutzerspezifische Konfiguration (Pfade, Kameras, DRX)
├── Start_Ingest.py           # Einstiegspunkt für DaVinci Resolve
│
└── _ingest_modules/          # Interner Modulordner für die Logik
    ├── __init__.py           # Markiert den Ordner als Python-Paket
    ├── config.py             # Konstanten, Wochentage und erlaubte Dateiendungen
    ├── utils.py              # Datei- und Hardware-Hilfsfunktionen (SD-Erkennung, Datums-Auslesung)
    ├── drive_ops.py          # Physikalische Ordnererstellung und Robocopy-Kopierprozess
    ├── resolve_media.py      # Resolve Media Pool Logik, Pancake-Generierung und NodeGraph-DRX-Grading
    └── proxy_generator.py    # NVIDIA NVENC-beschleunigte FFmpeg-Proxy-Generierung & Linking

```

---

## 🛠 Einrichtung & Konfiguration

### 1. Installation im Resolve-Skriptordner

Damit das Skript direkt aus Resolve heraus gestartet werden kann, platziere den gesamten Projektordner oder eine Verknüpfung der `Start_Ingest.py` im DaVinci Resolve Skriptverzeichnis:

* **Windows**: `C:\Users\<Dein_User>\AppData\Roaming\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\WorkflowIntegration\`

### 2. Konfiguration der Pfade & Kameras (`config.json`)

Passe die Datei `config.json` im Hauptverzeichnis an deine lokale Laufwerksstruktur an. Hier definierst du deine Quell- und Zielpfade sowie die Kameraerkennung:

```json
{
    "ALL_MEDIA_DIR": "D:\\Benutzer\\Jochen\\Videos",
    "BASE_TARGET_DIR": "D:\\Benutzer\\Jochen\\Videos\\01-Productions",
    "BASE_PROXY_DIR": "D:\\Benutzer\\Jochen\\Videos\\04-DR-Folders\\ProxyMedia",
    "BASE_DRX_DIR": "D:\\Benutzer\\Jochen\\Videos\\04-DR-Folders\\LUTs-AND-DRX",
    
    "camera_colors": {
        "LUMIX_S5II": "Orange",
        "LUMIX_S5D": "Apricot",
        "LUMIX": "Yellow",
        "DJI_MINI": "Green",
        "DJI_AVATA2": "Teal",
        "DJI_ACTION2": "Tan",
        "DJI": "Blue",
        "INSTA": "Purple",
        "REC709": "White"
    },

    "camera_mappings": [
        {
            "search_keywords": ["S5II", "S5M2", "GH6"],
            "camera_type": "LUMIX_S5II",
            "input_color_space": "Panasonic V-Gamut",
            "drx_profile": "FM-STD-Panasonic-VLOG.drx"
        },
        {
            "search_keywords": ["MINI", "MINI4", "MINI3", "M4P"],
            "camera_type": "DJI_MINI",
            "input_color_space": "DJI D-Gamut",
            "drx_profile": "FM-STD-DJI-DLOG-M.drx"
        },
        {
            "search_keywords": ["REC709", "GENERIC", "UNKNOWN", "SONY", "CANON"],
            "camera_type": "REC709",
            "input_color_space": "Rec.709",
            "drx_profile": ""
        }
    ]
}

```

* **`search_keywords`**: Erkennt die Kamera anhand von Begriffen im Volume-Label deiner SD-Karte.
* **`drx_profile`**: Name des exportierten Gradings aus Resolve, das im `BASE_DRX_DIR` liegt und automatisch via NodeGraph auf die Timeline-Clips angewendet wird.

---

## 💡 Workflow-Tipps

* **Benennung der SD-Karten**: Benenne deine SD-Karten im Explorer entsprechend deiner Keywords um (z. B. `CAM_S5II_A`, `DRONE_MINI4`), damit das Tool die Metadaten, Farben und DRX-Profile ab der ersten Sekunde vollautomatisch zuordnen kann.
* **Edit-Page Ready**: Da das Skript nach getaner Arbeit direkt auf die Edit-Page umschaltet, empfiehlt es sich, das "Pancake"-Prinzip (Timeline über Timeline) zu nutzen, um das sortierte Material extrem schnell in die Master-Timeline zu ziehen.

## Offene Todos
* Die Std-Node-Trees müssen noch vervollständigt werden bzgl. benutzter Kameras und Nodes für Kamera-Korrektur (und besserer Formatierung)
* Das DR-Projekt zur Erstellung der Std-Node-Trees muss noch ordentlich befüllt werden mit Testaufnahmen der Kameras (für Korrektur)