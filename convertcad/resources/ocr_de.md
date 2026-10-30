# OCR gescannter PDFs

ConvertCAD vektorisiert die Linien, Kreise und Bögen gescannter Zeichnungen und **liest ihren Text** mit den **PP-OCR**-Modellen von PaddleOCR, die RapidOCR und ONNX Runtime auf diesem Computer ausführen. Sie finden ganze Textzeilen überall auf dem Blatt — klein, gedreht, senkrecht oder von Linien gekreuzt. Keine Zeichnung verlässt den Computer.

## Sprachen

Wählen Sie sie unter *Einstellungen > Gescannte Seiten > OCR-Sprachen*:

| Auswahl | Liest | Modell |
|---|---|---|
| **Englisch, Französisch… (lateinische Schrift)** — Standard | Englisch, Französisch, Spanisch, Deutsch, Italienisch, Portugiesisch, Niederländisch, Polnisch, Türkisch, Vietnamesisch und 37 weitere Sprachen in lateinischer Schrift; außerdem Chinesisch und Japanisch | **integriert** (etwa 30 MB) |
| **Arabisch**, **Kyrillisch**, **Griechisch**, **Koreanisch**, **Devanagari**, **Thai**, **Tamil**, **Telugu** | diese Schrift (Arabisch liest auch Persisch und Urdu; Kyrillisch liest Russisch, Ukrainisch, Bulgarisch, Serbisch…) | Download |
| **Englisch, Französisch… + Arabisch** (oder eine andere Schrift) | Zeichnungen, die beide mischen, z. B. ein französischer Plan mit arabischem Schriftfeld: jede Zeile behält die Lesung ihrer eigenen Schrift | integriert + Download |

Nur die installierten Sprachen werden angezeigt. Eine Auswahl, deren Modell fehlt (von einem anderen Computer kopierte Einstellungen, entferntes Modell), bleibt sichtbar und ist mit *(nicht heruntergeladen)* gekennzeichnet: stattdessen wird das integrierte Modell verwendet, und der Bericht sagt es.

## Genauigkeit

- **Standard** (voreingestellt) — das integrierte Modell: schnell und die richtige Wahl für fast jede Zeichnung.
- **Maximal** — größere Modelle (Download, 132 MB): etwas besser bei schlechten Scans, aber etwa 20-mal langsamer (gemessen: 83 % der Beschriftungen eines Testblatts gelesen statt 81 %). Gilt für die Sprachen in lateinischer Schrift; die anderen Schriften haben jeweils ein Modell.

## Sprachen und Modelle herunterladen

*Einstellungen > Gescannte Seiten > OCR-Sprachen und -Modelle…* (auch im Menü *Werkzeuge*):

1. Wählen Sie ein Modell in der Liste (seine Größe wird angezeigt), dann **Herunterladen**. Ein Fortschrittsbalken verfolgt den Download; **Abbrechen** hält ihn an.
2. Jede Datei wird geprüft (SHA-256), bevor sie behalten wird: ein unterbrochener oder beschädigter Download hinterlässt nie ein fehlerhaftes Modell.
3. Danach funktioniert das Modell **offline, dauerhaft**. **Entfernen** löscht es.

Wo die Modelle gespeichert werden:

| ConvertCAD | Ordner |
|---|---|
| Windows (Installer oder portables Zip) | `%LOCALAPPDATA%\ConvertCAD\ocr_models` |
| Linux (AppImage, .deb, tar.gz) | `~/.local/share/convertcad/ocr_models` |
| Portabler Modus (eine leere Datei `ConvertCAD.portable` neben dem Programm) | der Ordner `ocr_models` neben dem Programm: die Modelle reisen mit |

Mit der Umgebungsvariable `CONVERTCAD_OCR_MODELS` lässt sich ein anderer Ordner wählen. Die Deinstallation von ConvertCAD unter Windows entfernt die heruntergeladenen Modelle; ein Update behält sie.

**Woher sie kommen:** aus der GitHub-Veröffentlichung `ocr-models-v1` von ConvertCAD, sonst aus dem Modell-Repository von RapidOCR (ModelScope). Nur die angeforderte Datei wird heruntergeladen; nichts wird gesendet, weder Zeichnungen noch Informationen über Sie. Ein Unternehmens-Proxy wird automatisch verwendet, wenn er im System (oder in der Variable `HTTPS_PROXY`) eingestellt ist.

**Computer ohne Internet:** öffnen Sie auf einem anderen Computer die Download-Seite (Schaltfläche *Download-Seite*), laden Sie die `.onnx`-Dateien des Modells herunter, kopieren Sie sie (USB-Stick…) und klicken Sie dann auf **Aus Datei installieren…** — die Dateien werden an ihrer Prüfsumme erkannt, unabhängig von ihrem Namen.

**Befehlszeile:** `ConvertCAD-cli --list-ocr` listet die Modelle auf, `ConvertCAD-cli --get-ocr-model arabic latin_max` lädt sie herunter, dann verwendet `--ocr-lang latin+arabic --ocr-quality maximum` sie.

## Tipps

- 300 dpi sind ein guter Standardwert. Verwenden Sie 400–600 dpi für kleinen Text auf großen Blättern (langsamer).
- Senkrechter Text wird ohne zusätzliche Einstellung gelesen.
- Ist ein gescanntes PDF bereits durchsuchbar (es enthält eine Textebene), verwendet ConvertCAD diesen Text statt der OCR.
- Aus dem Quellcode: `pip install -r requirements.txt` installiert RapidOCR, ONNX Runtime und das integrierte Modell.
