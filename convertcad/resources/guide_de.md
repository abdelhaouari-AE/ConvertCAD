# ConvertCAD Benutzerhandbuch

ConvertCAD wandelt 2D-PDF-Zeichnungen in **bearbeitbare DXF- oder DWG-Dateien aus echten CAD-Objekten** um: Linien, Polylinien, Bögen, Kreise, Splines, Schraffuren, Texte und Absätze, echte Bemaßungen, Führungslinien, Layer und Blöcke — kein Gewirr zerlegter Linien. Alles läuft auf Ihrem Computer.

## Die vier Schritte

1. **Eine Zeichnung öffnen** — *PDF öffnen…* (Strg+O), ein PDF auf das Fenster ziehen oder den Beispielplan ausprobieren. Jedes Blatt erscheint links mit einer Kennzeichnung: **Vektor** (ideal), **Scan** (wird vektorisiert und per OCR gelesen) oder **Leer**. Entfernen Sie den Haken bei Blättern, die nicht konvertiert werden sollen; das Auswahlmenü im Kopf von *Blätter* wählt alle, keine, nur Vektor- oder nur gescannte Blätter.
2. **Den Maßstab prüfen** — wählen Sie den Zeichnungsmaßstab unter *Einstellungen > Maßstab, Einheiten und Bereich* (ConvertCAD liest ihn aus dem Schriftfeld, wenn möglich). Für ein exaktes Ergebnis verwenden Sie **Kalibrieren** (C): klicken Sie zwei Punkte mit bekanntem realem Abstand an — zum Beispiel zwei Rasterachsen — und geben Sie den Abstand ein. Mit **Messen** (M) prüfen Sie vor dem Konvertieren jeden Abstand. Um nur einen Teil des Blatts zu konvertieren, verwenden Sie **Bereich wählen** (A) und ziehen ein Rechteck auf; *Ganzes Blatt* hebt dies auf.
3. **Konvertieren** (Strg+Eingabe) — läuft im Hintergrund; Sie können weiter zoomen oder jederzeit abbrechen.
4. **Prüfen und speichern** — die Registerkarte *DXF-Ergebnis* zeigt die konvertierte Zeichnung genau so, wie die CAD-Software sie lesen wird. **PDF überlagern** (O) legt das PDF darunter, mit einem Deckkraft-Regler: jeder Unterschied fällt sofort auf. Klicken Sie ein Objekt des Ergebnisses an, um es auszuwählen: es wird hervorgehoben, die Statusleiste zeigt Typ, Layer und Größe, und sein Layer wird unter *Layer* ausgewählt. Unter *Layer* entfernen Sie den Haken bei unerwünschten Layern, benennen sie um (Doppelklick) oder ändern ihre Farbe (Klick auf das Farbfeld); die Schaltfläche ↺ macht alle Layer-Änderungen rückgängig. Der *Bericht* listet alles Erzeugte mit den Warnungen auf. Dann **DXF speichern…** (Strg+S) — oder **DWG speichern…**: wählen Sie den Typ DWG im Speicherdialog, oder stellen Sie vor dem Konvertieren *Einstellungen > Ausgabe > Dateiformat* auf DWG.

## In der Zeichnung navigieren

| Aktion | So geht's |
|---|---|
| Zoom am Cursor | Mausrad |
| Ansicht verschieben | Ziehen mit der mittleren Taste, Leertaste + Ziehen, oder Ziehen mit dem Werkzeug Verschieben |
| Blatt einpassen | F |
| Seitenleiste ein- / ausklappen | Auf ihre Leiste am Fensterrand klicken; Strg+0 klappt beide ein (wie *Bildschirm bereinigen* in AutoCAD) |
| Nächstes / vorheriges Blatt | Bild ab / Bild auf |
| Ein Werkzeug abbrechen | Escape (Rechtsklick verwirft den ersten Punkt) |

Das Blatt bleibt bei jedem Zoom scharf: der sichtbare Bereich wird in Bildschirmauflösung neu gezeichnet.

## Objektfang

Beim Messen oder Kalibrieren springen die Klicks auf den exakten Punkt der Zeichnung, wie der Objektfang von AutoCAD. Die Statusleiste schaltet jeden Modus:

- **END** — Endpunkte und Ecken (quadratische Markierung)
- **MIT** — Mittelpunkte von Segmenten (Dreieck)
- **SCH** — Schnittpunkte (Kreuz)
- **ZEN** — Mittelpunkte von Kreisen und Bögen (Kreis)

F3 schaltet den Fang ein oder aus.

## Was die Konvertierung erzeugt

| Im PDF | Im DXF |
|---|---|
| Kreisförmige Kurven | Echte **ARC**- und **CIRCLE**-Objekte |
| Kurven aus mehreren Teilen | Ein exakter **SPLINE** |
| Sich berührende Segmente | Eine **LWPOLYLINE** (geschlossen, wenn sie eine Schleife bildet) |
| Strichmuster oder als einzelne Teile gezeichnete Striche | Eine Linie mit einem Linientyp **CENTER**, **DASHED**, **DASHDOT**, **PHANTOM**… auf dem PDF gemessen |
| Gefüllte Flächen | Volle **HATCH** auf dem Layer HATCH |
| Als viele parallele Linien gezeichnete Schraffur | Eine Muster-**HATCH** (Winkel und Abstand des PDF) |
| Sand, Beton, Kies, Erde, Ziegel, Dämmung oder Punkte, als viele Striche und Punkte gezeichnet | Eine **HATCH** mit dem Standardmuster (AR-SAND, AR-CONC, GRAVEL, EARTH, BRICK, INSUL, DOTS…) mit dem auf dem PDF gemessenen Maßstab und Winkel |
| Text | **TEXT** in der Schrift des PDFs (Arial, Times New Roman, Courier New, Calibri…, fett und kursiv), mit ihrer Größe und Länge; gestapelte Zeilen werden ein **MTEXT**-Absatz, links, zentriert oder rechts ausgerichtet wie im PDF |
| Als Striche gezeichneter AutoCAD-SHX-Text | Echter **TEXT** auf dem Layer TEXT_SHX (die Striche bleiben auf dem ausgeblendeten Layer TEXT_SHX_STROKES) |
| Pfeil + Linie + Pfeil + Wert | Echte **DIMENSION** (Layer DIM) — der Wert behält den PDF-Text |
| Schrägstriche + Linie + Wert | Echte **DIMENSION** mit Architekturstrichen |
| Pfeil auf einem Kreis oder Bogen + Wert „R…“ / „Ø…“ | Echte **RADIUS**- / **DURCHMESSER**-Bemaßung |
| Zwei Pfeile auf einem Bogen + ein Winkel („45°“) oder eine Bogenlänge | Echte **WINKEL**- / **BOGENLÄNGEN**-Bemaßung — nur wenn der Wert zum gezeichneten Bogen passt |
| Pfeil + Linie + Notiz | **LEADER** / Multi-Führungslinie (Layer ANNOT_LEADER) |
| Identische wiederholte Symbole, auch um beliebige Winkel gedreht oder gespiegelt | Ein **BLOCK** + ein INSERT je Vorkommen |
| Gescannte Blätter | **LINE**, **CIRCLE** und **ARC** auf dem Layer TRACE_LINES, Text per OCR gelesen |
| Eingebettete Bilder, Scans | Bild auf dem gesperrten Layer IMG_RASTER |

Maßtexte, die zu keiner Bemaßung passen, kommen auf den Layer **DIM_RAW** (rot), damit Sie sie prüfen können. Nichts wird erfunden: ein Muster oder eine Bemaßung wird nur rekonstruiert, wenn es das PDF wiedergibt; sonst bleiben seine Teile unverändert. Die Bogenlängenbemaßung wird ab DXF 2007 als echte ARC_DIMENSION geschrieben; bei älteren Versionen und DWG bleibt sie als Zeichnung auf dem Layer DIM erhalten.

## Die Einstellungen

**Maßstab, Einheiten und Bereich** — Zeichnungsmaßstab (1:N, oder 1/4" = 1'-0" und 1" = 20' in Zoll und Fuß) und DXF-Einheit (mm, cm, m, Zoll, Fuß); *Bereich wählen… / Ganzes Blatt* (nur der Bereich wird konvertiert, in den eigenen Koordinaten des Blatts; der Bereich gilt für jedes konvertierte Blatt). *Den auf jedem Blatt angegebenen Maßstab lesen* ist für Plansätze mit unterschiedlichen Maßstäben (Grundriss 1:100, Details 1:20): jedes Blatt verwendet den Maßstab seines Schriftfelds, und der obige Maßstab gilt, wenn ein Blatt keinen oder mehrere angibt; der Bericht nennt den Maßstab jedes Blatts. Die Kalibrierung ersetzt beides; der Bereich zeigt den entsprechenden Maßstab („etwa 1:100,2“) zur Kontrolle.

**Geometrie** — Bögen und Kreise rekonstruieren; Segmente zu Polylinien verbinden; Kurven zu einzelnen Splines verbinden; *Kurvengenauigkeit* (Fein / Normal / Grob) legt fest, wie genau eine Kurve einem Kreis entsprechen muss; volle Füllungen als Schraffuren; *Schraffurmuster rekonstruieren* (parallele Linien → Muster-HATCH; Sand, Beton, Kies, Erde, Ziegel, Dämmung, Punkte → das Standardmuster; Sand und Beton wirken zufällig, daher werden ihr Maßstab und ihre Lage geschätzt, und der Bericht sagt es); *gestrichelte Linien rekonstruieren* (einzelne Striche → eine Linie mit Linientyp); weiße Masken, weiße Linien und Seitenhintergründe ignorieren (sie würden die Zeichnung im CAD verdecken).

**Text** — Text exportieren; gestapelte Zeilen zu MTEXT-Absätzen gruppieren; *Verhältnis der Texthöhe* (Großbuchstabenhöhe ÷ PDF-Schriftgröße) für Schriften, die ConvertCAD nicht erkennt — erkannte Schriften behalten ihre eigene Größe; eine Änderung gilt für alle Texte; *als Striche oder Umrisse gezeichneten Text wiederherstellen*: AutoCAD-SHX-Text wird dank der versteckten Kommentare, die AutoCAD seinen PDFs hinzufügt, wieder zu echtem Text (Layer TEXT_SHX), und als gefüllte Umrisse gezeichneter TrueType-Text wird durch seinen echten Text ersetzt.

**Bemaßungen und Führungslinien** — Bemaßungen mit Pfeilen (linear, Radius, Durchmesser, Winkel, Bogenlänge) und/oder mit Schrägstrichen rekonstruieren; Führungslinien rekonstruieren.

**Layer und Blöcke** — die eigenen Layer des PDF beibehalten, wenn es welche hat; *Layer-Benennung*, wenn nicht: Farbe + Linienstärke + Linientyp (z. B. GEO_BLACK_050_CENTER), nur Farbe oder ein einziger Layer; Linientypen erkennen; *Farben*: AutoCAD-Farbindex (funktioniert mit CTB-Plotstilen) oder Echtfarbe (exaktes RGB); wiederholte Symbole als Blöcke erkennen, mit einer Mindestanzahl an Vorkommen, und *auch gedrehte und gespiegelte Kopien erkennen* (jeder Winkel).

**Gescannte Seiten** — Linien, Kreise und Bögen vektorisieren; Text per OCR lesen (PP-OCR-Modelle, auf diesem Computer); *OCR-Sprachen*: Englisch, Französisch… (lateinische Schrift, integriert), eine andere Schrift (Arabisch, Kyrillisch, Griechisch…) oder beide für gemischte Zeichnungen — nur die installierten werden angezeigt; *OCR-Genauigkeit*: Standard (integriertes Modell) oder Maximal (größere Modelle, langsamer); **OCR-Sprachen und -Modelle…** lädt die anderen Sprachen und die Modelle für maximale Genauigkeit herunter oder installiert sie auf einem Computer ohne Internet aus Dateien (siehe *Hilfe > OCR-Anleitung*); Scan-Auflösung (200–600 dpi); die Textebene des PDF verwenden, wenn der Scan bereits durchsuchbar ist; Rasterbilder auf einem gesperrten Layer behalten.

**Ausgabe** — *Dateiformat*: DXF oder DWG (AutoCAD-2000-Format: öffnet sich in jedem AutoCAD seit 2000 und in jeder aktuellen CAD-Software; geschrieben vom enthaltenen Konverter GNU LibreDWG und nach dem Schreiben geprüft); DXF-Version (R2018 für aktuelle Software, R12 für alte CNC-Maschinen); bei mehreren Blättern ein DXF mit den Blättern nebeneinander oder ein DXF pro Blatt; ein Konvertierungsprotokoll neben das DXF schreiben; den Ordner nach dem Speichern öffnen.

**Profile** — fertige Einstellungen: Empfohlen, Architekturpläne, Tragwerks- / Schalungspläne, Gescannte Archivzeichnungen, Nur Geometrie, CNC / Laser. *Als Profil speichern…* bewahrt Ihre eigenen Kombinationen.

## Sprache der Oberfläche

*Ansicht > Sprache*: English, Français, Español, Deutsch oder العربية (Arabisch, von rechts nach links geschrieben: das ganze Fenster wird gespiegelt, die Zeichnungen nicht). Die Änderung gilt beim nächsten Start. Die OCR-Sprachen werden getrennt gewählt (*Einstellungen > Gescannte Seiten*).

## Updates

ConvertCAD verbindet sich nie von selbst mit dem Internet. *Hilfe > Nach Updates suchen…* fragt GitHub einmal, ob es eine neuere Version gibt; *Hilfe > Beim Start nach Updates suchen* tut dies bei jedem Start (standardmäßig aus). Nichts wird gesendet und nichts wird installiert: gibt es eine neuere Version, zeigt ConvertCAD ihre Nummer und kann ihre Veröffentlichungsseite öffnen.

## Einen ganzen Ordner konvertieren

*Ordner konvertieren…* (Strg+B) konvertiert jedes PDF eines Ordners (wahlweise mit Unterordnern) mit den aktuellen Einstellungen. Jede Datei erhält ihr DXF (oder DWG) und ihr Protokoll im Ausgabeordner. Die Kalibrierung gilt in diesem Modus nicht: standardmäßig verwendet jedes Blatt den in seinem Schriftfeld angegebenen Maßstab, sonst den Zeichnungsmaßstab der Einstellungen — prüfen Sie ihn in jedem Protokoll.

Dieselben Konvertierungen lassen sich mit dem Konsolenprogramm *ConvertCAD-cli.exe* (neben ConvertCAD.exe) automatisieren — geben Sie `ConvertCAD-cli --help` in einer Eingabeaufforderung ein.

## Kontrolle nach jeder Konvertierung

1. Messen Sie im CAD einen bekannten Abstand, um den Maßstab zu bestätigen.
2. Zeigen Sie nur den Layer DIM und vergleichen Sie einige Werte mit dem PDF.
3. Prüfen Sie den Layer DIM_RAW.
4. Lesen Sie die Warnungen des Berichts.

## Fehlerbehebung

- **Text kommt als kleine Striche an** — das PDF wurde mit SHX-Schriften ohne die versteckten Kommentare erzeugt (kein AutoCAD-PDF, oder ohne sie exportiert): die Striche bleiben Geometrie. Lassen Sie bei AutoCAD-PDFs *Als Striche oder Umrisse gezeichneten Text wiederherstellen* eingeschaltet.
- **Eine weiße Fläche verdeckt die Zeichnung im CAD** — lassen Sie *Weiße Masken, weiße Linien und Seitenhintergründe ignorieren* eingeschaltet.
- **Die OCR ist schlecht** — prüfen Sie die *OCR-Sprachen* (eine kyrillische oder arabische Zeichnung braucht ihre Schrift: *OCR-Sprachen und -Modelle…*); wählen Sie bei schlechten Scans oder kleinem Text *OCR-Genauigkeit: Maximal* oder eine höhere Scan-Auflösung; siehe *Hilfe > OCR-Anleitung*.
- **Ein OCR-Download schlägt fehl** — prüfen Sie die Internetverbindung oder den Proxy des Unternehmens; auf einem Computer ohne Internet verwenden Sie *Aus Datei installieren…* (siehe *Hilfe > OCR-Anleitung*).
- **Das DWG konnte nicht geschrieben werden** — der Bericht nennt den Grund, und die Zeichnung wird stattdessen als DXF gespeichert; senden Sie das PDF mit dem Protokoll, wenn es wieder vorkommt.
- **Zu viele kleine Layer** — wählen Sie *Nur Farbe* oder *Ein einziger Geometrie-Layer*, oder entfernen Sie vor dem Speichern Haken bei Layern.
- **Ein wiederholtes Symbol wurde kein Block** — seine Kopien unterscheiden sich (Größe, ein fehlendes Teil) oder es kommt seltener vor als die *Mindestanzahl der Vorkommen*.
- **Eine Schraffur blieb als viele kleine Linien** — sie passte zu keinem Standardmuster genau genug (eigenes Muster, mehrere sich berührende Muster): ihre Teile bleiben erhalten, nichts wird erfunden.
- **Eine Konvertierung ist langsam** — sehr große Scans: senken Sie die Scan-Auflösung.

ConvertCAD {APP_VERSION} — © {APP_YEAR} {APP_AUTHOR}
