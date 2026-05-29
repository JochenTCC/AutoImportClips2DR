# AutoImportClips2DR

Ein Automatisierungstool für DaVinci Resolve, um SD-Karten-Backups, Dateisortierung und Proxy-Erstellung mit NVIDIA-Beschleunigung effizient abzuwickeln.

---

## 🚀 Funktionen
* **Automatisierte Ordnerstruktur**: Sortierung nach Datum, Wochentag oder Projekttagen.
* **Intelligentes Proxy-Handling**: Nutzt NVIDIA NVENC für extrem schnelles Proxy-Rendering (H.265/H.264).
* **DaVinci Resolve Integration**: Importiert Clips direkt in die korrekten Media-Pool-Bins.
* **Sicherer Workflow**: Verhindert redundante Prozesse durch Dateiprüfung.

---

## 🛠 Voraussetzungen
* **DaVinci Resolve** (Studio oder Free)
* **FFmpeg**: Muss im System-PATH installiert sein.
    * *Prüfung*: Gib in der CMD `ffmpeg -version` ein.
* **Python 3.x**: Muss auf dem System vorhanden sein.

---

## ⚙️ Installation & Einrichtung

### 1. Vorbereitung
Klonen oder lade das Repository in ein Verzeichnis deiner Wahl.

### 2. Konfiguration
Passe die Pfade in der `config.json` an deine lokale Struktur an:
```json
{
    "ALL_MEDIA_DIR": "D:\\Videos",
    "BASE_TARGET_DIR": "D:\\Videos\\01-Productions",
    "BASE_PROXY_DIR": "D:\\Videos\\04-DR-Folders\\ProxyMedia"
}
