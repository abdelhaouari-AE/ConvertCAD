"""
i18n.py — English / French interface strings.

The English text IS the key: write tr("Open PDF…") in the code and add its
French version to FR below. A missing translation simply shows English, so
the interface never breaks. The language is chosen in View > Language and
applies at the next start (the user is told so).

Long texts (user guide, terms of use) live in convertcad/resources as
guide_en.md / guide_fr.md / terms_en.md / terms_fr.md.
"""

import re
from typing import Dict

_LANG = "en"


def set_language(lang: str) -> None:
    global _LANG
    _LANG = lang if lang in ("en", "fr") else "en"


def language() -> str:
    return _LANG


def tr(text: str, **kwargs) -> str:
    """Translate `text` to the current language, then format {placeholders}."""
    if _LANG == "fr":
        text = FR.get(text, text)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def tr_progress(msg: str) -> str:
    """Translate a progress message coming from the engine.

    The engine (convertcad/core) never imports the interface, so it reports
    progress in English, e.g. "Page 1/2: rebuilding geometry…". This function
    recognises those few message shapes and translates them for the activity
    log and the status bar. Unknown messages are shown unchanged.
    """
    if _LANG == "en" or not msg:
        return msg
    m = re.match(r"^\[(\d+)/(\d+)\] (.*?) — (.*)$", msg, re.S)   # batch
    if m:
        return f"[{m.group(1)}/{m.group(2)}] {m.group(3)} — " \
               f"{tr_progress(m.group(4))}"
    m = re.match(r"^Page (\d+)/(\d+): (.*)$", msg, re.S)
    if m:
        return tr("Page {pno}/{total}: {msg}", pno=m.group(1),
                  total=m.group(2), msg=tr_progress(m.group(3)))
    m = re.match(r"^scanned page — tracing at (\d+) dpi( \+ OCR)?…$", msg)
    if m:
        return tr("scanned page — tracing at {dpi} dpi{ocr}…",
                  dpi=m.group(1), ocr=" + OCR" if m.group(2) else "")
    m = re.match(r"^Saving (.*)…$", msg, re.S)
    if m:
        return tr("Saving {name}…", name=m.group(1))
    return tr(msg)


def tr_paper(text: str) -> str:
    """'A3 landscape' -> 'A3 paysage' (paper names come from the engine)."""
    if _LANG == "en" or not text:
        return text
    for word in ("landscape", "portrait"):
        if text.endswith(" " + word):
            return text[: -len(word)] + tr(word)
    return text


FR: Dict[str, str] = {}          # filled at the bottom of this module


def _fr(pairs: Dict[str, str]) -> None:
    FR.update(pairs)


# ---------------------------------------------------------------------------
# French translations (kept in one place; grouped by area of the interface)
# ---------------------------------------------------------------------------
_fr({
    # ---- menus ----
    "&File": "&Fichier", "&View": "&Affichage", "&Tools": "&Outils",
    "&Help": "&Aide",
    "Open PDF…": "Ouvrir un PDF…", "Open recent": "Fichiers récents",
    "Clear the list": "Vider la liste", "No recent file": "Aucun fichier récent",
    "Open the sample plan": "Ouvrir le plan d'exemple",
    "Close the drawing": "Fermer le dessin",
    "Convert": "Convertir", "Convert again": "Reconvertir",
    "Cancel": "Annuler", "Save DXF…": "Enregistrer le DXF…",
    "Convert a folder…": "Convertir un dossier…",
    "Save the report…": "Enregistrer le rapport…", "Exit": "Quitter",
    "Fit the sheet": "Ajuster la feuille", "Zoom in": "Zoom avant",
    "Zoom out": "Zoom arrière", "Source PDF": "PDF source",
    "DXF result": "Résultat DXF", "Panels": "Panneaux",
    "Sheets panel": "Panneau des feuilles",
    "Settings panel": "Panneau des réglages",
    "Activity panel": "Panneau d'activité", "Theme": "Thème",
    "Dark": "Sombre", "Light": "Clair", "Language": "Langue",
    "Pan": "Déplacer", "Calibrate scale": "Étalonner l'échelle",
    "Measure distance": "Mesurer une distance",
    "Clear measurements": "Effacer les mesures",
    "Reset calibration": "Réinitialiser l'étalonnage",
    "Object snap": "Accrochage aux objets", "Endpoint": "Extrémité",
    "Midpoint": "Milieu", "Intersection": "Intersection",
    "Center": "Centre", "User guide": "Guide d'utilisation",
    "Keyboard shortcuts": "Raccourcis clavier",
    "OCR setup (scanned PDFs)": "Configuration de l'OCR (PDF scannés)",
    "Terms of use": "Conditions d'utilisation",
    "About ConvertCAD": "À propos de ConvertCAD",
    "Open the settings folder": "Ouvrir le dossier des paramètres",
    # ---- command bar tooltips ----
    "Open a PDF drawing (Ctrl+O)": "Ouvrir un dessin PDF (Ctrl+O)",
    "Pan and zoom the view (Esc)": "Déplacer et zoomer la vue (Échap)",
    "Click two points with a known distance to set the exact scale (C)":
        "Cliquer deux points de distance connue pour fixer l'échelle exacte (C)",
    "Click two points to measure a real distance (M)":
        "Cliquer deux points pour mesurer une distance réelle (M)",
    "Convert the selected sheets to DXF (Ctrl+Enter)":
        "Convertir les feuilles sélectionnées en DXF (Ctrl+Entrée)",
    "Save the reviewed DXF (Ctrl+S)": "Enregistrer le DXF vérifié (Ctrl+S)",
    "Convert every PDF of a folder (Ctrl+B)":
        "Convertir tous les PDF d'un dossier (Ctrl+B)",
    "Switch between dark and light theme":
        "Basculer entre thème sombre et clair",
    "Stop the running conversion": "Arrêter la conversion en cours",
    # ---- empty state ----
    "Drop a PDF drawing here": "Déposez un dessin PDF ici",
    "Vector PDFs exported from CAD give the best result. Scanned drawings are traced and read with OCR.":
        "Les PDF vectoriels exportés d'un logiciel de CAO donnent le meilleur "
        "résultat. Les plans scannés sont vectorisés et lus par OCR.",
    "Open a drawing": "Ouvrir un dessin", "Check the scale": "Vérifier l'échelle",
    "Review and save": "Vérifier et enregistrer",
    "Recent drawings": "Dessins récents",
    "Try the sample plan": "Essayer le plan d'exemple",
    # ---- panels ----
    "Sheets": "Feuilles", "All": "Toutes", "None": "Aucune",
    "Vector only": "Vectorielles",
    "Include this sheet in the conversion":
        "Inclure cette feuille dans la conversion",
    "Vector": "Vectoriel", "Scan": "Scan", "Empty": "Vide",
    "Rotated {deg}°": "Tournée {deg}°",
    "{n} of {total} sheets selected": "{n} feuille(s) sur {total} sélectionnée(s)",
    "Settings": "Réglages", "Layers": "Calques", "Report": "Rapport",
    "Activity": "Activité", "Clear": "Effacer",
    # ---- options ----
    "Preset": "Préréglage", "Save as preset…": "Enregistrer comme préréglage…",
    "Delete preset": "Supprimer le préréglage",
    "Reset to defaults": "Valeurs par défaut",
    "Scale and units": "Échelle et unités", "Drawing scale": "Échelle du dessin",
    "Units": "Unités", "Millimetres (mm)": "Millimètres (mm)",
    "Centimetres (cm)": "Centimètres (cm)", "Metres (m)": "Mètres (m)",
    "Not calibrated: the drawing scale above is used.":
        "Non étalonné : l'échelle ci-dessus est utilisée.",
    "Calibrated: 1 pt = {v} {u} (about 1:{den})":
        "Étalonné : 1 pt = {v} {u} (environ 1:{den})",
    "Calibrate…": "Étalonner…", "Reset": "Réinitialiser",
    "Geometry": "Géométrie",
    "Rebuild arcs and circles": "Reconstruire arcs et cercles",
    "Join segments into polylines": "Joindre les segments en polylignes",
    "Join curves into single splines": "Joindre les courbes en splines uniques",
    "Curve precision": "Précision des courbes", "Fine": "Fine",
    "Normal": "Normale", "Loose": "Large",
    "Solid fills as hatches": "Remplissages en hachures pleines",
    "Ignore white masks and page backgrounds":
        "Ignorer les masques blancs et fonds de page",
    "Text": "Texte", "Export text": "Exporter le texte",
    "Group stacked lines into paragraphs (MTEXT)":
        "Regrouper les lignes empilées en paragraphes (MTEXT)",
    "Text height ratio": "Rapport de hauteur du texte",
    "Recover AutoCAD SHX text (experimental)":
        "Récupérer le texte SHX AutoCAD (expérimental)",
    "Dimensions and leaders": "Cotes et lignes de repère",
    "Dimensions with arrows": "Cotes avec flèches",
    "Dimensions with tick marks": "Cotes avec traits obliques",
    "Leaders (arrow + note)": "Lignes de repère (flèche + note)",
    "Values always keep the original PDF text. Unmatched values go to layer DIM_RAW for review.":
        "Les valeurs gardent toujours le texte d'origine du PDF. Les valeurs "
        "non reconnues vont sur le calque DIM_RAW pour vérification.",
    "Layers and blocks": "Calques et blocs",
    "Keep the PDF's own layers": "Conserver les calques du PDF",
    "Layer naming": "Nom des calques",
    "Colour + lineweight + linetype": "Couleur + épaisseur + type de ligne",
    "Colour only": "Couleur seule", "Single geometry layer": "Un seul calque",
    "Recognise linetypes (axis, hidden…)":
        "Reconnaître les types de ligne (axe, caché…)",
    "Colours": "Couleurs", "AutoCAD Color Index": "Index de couleur AutoCAD",
    "True colour (exact RGB)": "Couleur vraie (RVB exact)",
    "Detect repeated symbols as blocks":
        "Détecter les symboles répétés comme blocs",
    "Minimum occurrences": "Occurrences minimales",
    "Scanned pages": "Pages scannées",
    "Trace lines and circles": "Vectoriser lignes et cercles",
    "Read text with OCR": "Lire le texte par OCR",
    "OCR language": "Langue de l'OCR",
    "Also read vertical text (slower)":
        "Lire aussi le texte vertical (plus lent)",
    "Scan resolution": "Résolution de lecture",
    "Use the PDF's existing text layer": "Utiliser la couche texte du PDF",
    "Keep raster images (locked layer)":
        "Conserver les images (calque verrouillé)",
    "OCR ready: Tesseract {v}": "OCR prêt : Tesseract {v}",
    "OCR not available: Tesseract was not found. Tracing still works.":
        "OCR indisponible : Tesseract introuvable. La vectorisation "
        "fonctionne quand même.",
    "Output": "Sortie", "DXF version": "Version DXF",
    "Multi-page output": "Sortie multipage",
    "One DXF, sheets side by side": "Un DXF, feuilles côte à côte",
    "One DXF per sheet": "Un DXF par feuille",
    "Write a conversion log next to the DXF":
        "Écrire un journal de conversion à côté du DXF",
    "Open the folder after saving": "Ouvrir le dossier après l'enregistrement",
    "Options changed since the last conversion. Convert again to update the result.":
        "Les options ont changé depuis la dernière conversion. Reconvertissez "
        "pour mettre à jour le résultat.",
    # ---- option tooltips ----
    "Scale of the PDF sheet, e.g. 1:100. Ignored when the drawing is calibrated.":
        "Échelle de la feuille PDF, par ex. 1:100. Ignorée si le dessin est "
        "étalonné.",
    "Real-world unit of the DXF coordinates.":
        "Unité réelle des coordonnées du DXF.",
    "PDF curves that are circular become true ARC and CIRCLE entities.":
        "Les courbes circulaires du PDF deviennent de vrais ARCS et CERCLES.",
    "Touching segments with the same style become one polyline.":
        "Les segments jointifs de même style deviennent une seule polyligne.",
    "Curves drawn in several pieces become one exact SPLINE.":
        "Les courbes en plusieurs morceaux deviennent une SPLINE exacte.",
    "How strictly a curve must match a circle to become an arc.":
        "Tolérance pour qu'une courbe soit reconnue comme un arc.",
    "Filled areas become solid HATCH entities on layer HATCH.":
        "Les zones remplies deviennent des HACHURES pleines (calque HATCH).",
    "Skips white masks and page-sized backgrounds, which would hide the drawing in CAD.":
        "Ignore les masques blancs et les fonds de page qui masqueraient le "
        "dessin dans la CAO.",
    "PDF text becomes editable TEXT entities.":
        "Le texte du PDF devient des entités TEXTE modifiables.",
    "Left-aligned lines of the same size become one MTEXT paragraph (notes, title block).":
        "Les lignes alignées de même taille deviennent un paragraphe MTEXT "
        "(notes, cartouche).",
    "Cap height relative to the PDF font size. 0.70 suits most CAD fonts.":
        "Hauteur des majuscules par rapport à la taille de police. 0,70 "
        "convient à la plupart des polices CAO.",
    "AutoCAD stores SHX text as hidden comments; they are placed on layer TEXT_SHX. Positions are approximate.":
        "AutoCAD stocke le texte SHX en commentaires cachés ; ils sont placés "
        "sur le calque TEXT_SHX. Positions approximatives.",
    "Arrow + line + arrow + value becomes a real DIMENSION entity.":
        "Flèche + ligne + flèche + valeur devient une vraie entité COTE.",
    "Architectural dimensions with oblique ticks become DIMENSION entities.":
        "Les cotes architecturales à traits obliques deviennent des COTES.",
    "Arrow + line + note becomes a leader.":
        "Flèche + ligne + note devient une ligne de repère.",
    "Layers already present in the PDF keep their names.":
        "Les calques présents dans le PDF gardent leur nom.",
    "How geometry layers are created when the PDF has no layers.":
        "Mode de création des calques quand le PDF n'en contient pas.",
    "Dash patterns become CENTER, DASHED, DASHDOT or PHANTOM linetypes.":
        "Les tirets deviennent les types de ligne CENTER, DASHED, DASHDOT ou "
        "PHANTOM.",
    "ACI colours work with CTB plot styles; true colour keeps the exact PDF colour.":
        "Les couleurs ACI fonctionnent avec les styles de tracé CTB ; la "
        "couleur vraie garde la couleur exacte du PDF.",
    "Identical symbols repeated on the sheet become one BLOCK with insertions.":
        "Les symboles identiques répétés deviennent un BLOC avec insertions.",
    "A symbol must appear at least this many times to become a block.":
        "Nombre minimal d'apparitions pour qu'un symbole devienne un bloc.",
    "Scanned pages are vectorised (lines, circles) on layer TRACE_LINES.":
        "Les pages scannées sont vectorisées (lignes, cercles) sur le calque "
        "TRACE_LINES.",
    "Text on scanned pages is recognised with Tesseract OCR.":
        "Le texte des pages scannées est reconnu par l'OCR Tesseract.",
    "A second OCR pass reads text written bottom-to-top.":
        "Une seconde passe OCR lit le texte écrit de bas en haut.",
    "Higher resolution traces finer details but takes longer.":
        "Une résolution plus élevée trace plus de détails mais prend plus de "
        "temps.",
    "When a scanned PDF is already searchable, its text is used instead of OCR.":
        "Si le PDF scanné contient déjà du texte, il est utilisé à la place "
        "de l'OCR.",
    "Embedded images and scans are kept on the locked layer IMG_RASTER for checking.":
        "Les images et scans sont conservés sur le calque verrouillé "
        "IMG_RASTER pour vérification.",
    "R2018 suits current CAD software; R12 suits old CNC machines.":
        "R2018 convient aux logiciels récents ; R12 aux anciennes machines "
        "CNC.",
    "With several sheets: one file with sheets side by side, or one file per sheet.":
        "Avec plusieurs feuilles : un fichier côte à côte, ou un fichier par "
        "feuille.",
    # ---- layers panel ----
    "Filter layers": "Filtrer les calques", "Keep": "Garder",
    "Colour": "Couleur", "Layer": "Calque", "Linetype": "Type de ligne",
    "Entities": "Entités", "Show all": "Tout afficher", "Hide all": "Tout masquer",
    "Undo changes": "Annuler les modifications",
    "Unchecked layers are hidden here and removed from the saved DXF. Double-click a name to rename it, click a colour to change it.":
        "Les calques décochés sont masqués ici et retirés du DXF enregistré. "
        "Double-cliquez un nom pour le renommer, cliquez une couleur pour la "
        "changer.",
    "Convert a drawing to review its layers here.":
        "Convertissez un dessin pour vérifier ses calques ici.",
    "Layer colour": "Couleur du calque", "was": "anciennement",
    # ---- report panel ----
    "Convert a drawing to see its report here.":
        "Convertissez un dessin pour voir son rapport ici.",
    "Save log…": "Journal…", "Save as HTML…": "Enregistrer en HTML…",
    "Copy": "Copier", "Copied to the clipboard.": "Copié dans le presse-papiers.",
    # ---- status bar ----
    "Sheet": "Feuille", "Paper": "Format", "Scale": "Échelle",
    "Cursor": "Curseur", "Snap": "Accrochage", "Zoom": "Zoom",
    "Calibrated": "Étalonnée", "Ready": "Prêt",
    "END": "EXT", "MID": "MIL", "INT": "INT", "CEN": "CEN",
    "Snap to endpoints": "Accrocher aux extrémités",
    "Snap to midpoints": "Accrocher aux milieux",
    "Snap to intersections": "Accrocher aux intersections",
    "Snap to circle centres": "Accrocher aux centres des cercles",
    # ---- tools / messages ----
    "Calibration: click the first point.":
        "Étalonnage : cliquez le premier point.",
    "Calibration: click the second point.":
        "Étalonnage : cliquez le second point.",
    "Measure: click the first point.": "Mesure : cliquez le premier point.",
    "Measure: click the second point.": "Mesure : cliquez le second point.",
    "Distance {d}   ΔX {dx}   ΔY {dy}   Angle {a}°":
        "Distance {d}   ΔX {dx}   ΔY {dy}   Angle {a}°",
    "Real distance between the two points":
        "Distance réelle entre les deux points",
    "Measured on the sheet: {mm} mm of paper.":
        "Mesuré sur la feuille : {mm} mm de papier.",
    "Resulting scale: about 1:{den}": "Échelle obtenue : environ 1:{den}",
    "Apply": "Appliquer", "Enter a distance greater than zero.":
        "Saisissez une distance supérieure à zéro.",
    "Scale calibrated: about 1:{den}.": "Échelle étalonnée : environ 1:{den}.",
    "Calibration removed: the drawing scale is used.":
        "Étalonnage supprimé : l'échelle du dessin est utilisée.",
    "Opening {name}…": "Ouverture de {name}…",
    "Opened {name}: {pages} sheet(s).": "{name} ouvert : {pages} feuille(s).",
    "Cannot open this PDF.": "Impossible d'ouvrir ce PDF.",
    "This PDF is password-protected. Remove the password (print it to PDF) and try again.":
        "Ce PDF est protégé par mot de passe. Retirez le mot de passe "
        "(imprimez-le en PDF) puis réessayez.",
    "Only PDF files can be opened.": "Seuls les fichiers PDF peuvent être ouverts.",
    "Select at least one sheet to convert.":
        "Sélectionnez au moins une feuille à convertir.",
    "Converting…": "Conversion…", "Cancelling…": "Annulation…",
    "Conversion cancelled.": "Conversion annulée.",
    "Converted in {s} s: {n} entities on {l} layers. Review the result, then save the DXF.":
        "Converti en {s} s : {n} entités sur {l} calques. Vérifiez le "
        "résultat puis enregistrez le DXF.",
    "Conversion failed. See the report for details.":
        "La conversion a échoué. Voir le rapport pour le détail.",
    "Saved {name}.": "{name} enregistré.",
    "Saved {n} files in {folder}.": "{n} fichiers enregistrés dans {folder}.",
    "Could not save the DXF: {err}": "Impossible d'enregistrer le DXF : {err}",
    "Rendering the DXF preview…": "Rendu de l'aperçu DXF…",
    "Large drawing: the preview may take a few seconds.":
        "Dessin volumineux : l'aperçu peut prendre quelques secondes.",
    "No result yet. Convert the drawing to preview the DXF here.":
        "Pas encore de résultat. Convertissez le dessin pour voir le DXF ici.",
    "Sheet file": "Fichier", "Unsaved result": "Résultat non enregistré",
    "The conversion is still running. Quit anyway?":
        "La conversion est en cours. Quitter quand même ?",
    "The result has not been saved. Quit anyway?":
        "Le résultat n'a pas été enregistré. Quitter quand même ?",
    "The result has not been saved. Open another drawing anyway?":
        "Le résultat n'a pas été enregistré. Ouvrir un autre dessin quand "
        "même ?",
    "Language changed. Restart ConvertCAD to apply it.":
        "Langue modifiée. Redémarrez ConvertCAD pour l'appliquer.",
    "Preset name": "Nom du préréglage",
    "Preset \"{name}\" saved.": "Préréglage « {name} » enregistré.",
    "Preset \"{name}\" applied.": "Préréglage « {name} » appliqué.",
    "Built-in": "Intégré", "My presets": "Mes préréglages",
    "Recommended (all features)": "Recommandé (toutes les fonctions)",
    "Architectural plans (tick dimensions)":
        "Plans d'architecture (cotes à traits obliques)",
    "Structural / formwork plans": "Plans de structure / coffrage",
    "Scanned archive drawings (OCR)": "Plans d'archive scannés (OCR)",
    "Geometry only (no annotations)": "Géométrie seule (sans annotations)",
    "CNC / laser (R12, single layer, no text)":
        "CNC / laser (R12, un calque, sans texte)",
    "Modified": "Modifié",
    # ---- batch ----
    "Convert a folder": "Convertir un dossier",
    "Folder of PDF drawings": "Dossier des plans PDF",
    "Output folder for the DXF files": "Dossier de sortie des DXF",
    "Browse…": "Parcourir…", "Include sub-folders": "Inclure les sous-dossiers",
    "File": "Fichier", "Status": "État", "Time": "Durée",
    "Waiting": "En attente", "Converting": "Conversion", "Done": "Terminé",
    "Failed": "Échec", "Start": "Démarrer", "Close": "Fermer",
    "Open the output folder": "Ouvrir le dossier de sortie",
    "Uses the current settings. Calibration does not apply: each drawing uses the drawing scale.":
        "Utilise les réglages actuels. L'étalonnage ne s'applique pas : "
        "chaque dessin utilise l'échelle du dessin.",
    "{n} PDF file(s) found.": "{n} fichier(s) PDF trouvé(s).",
    "No PDF file in this folder.": "Aucun fichier PDF dans ce dossier.",
    "{ok} of {total} converted.": "{ok} sur {total} converti(s).",
    # ---- dialogs ----
    "I accept": "J'accepte", "Decline and quit": "Refuser et quitter",
    "Version {v}": "Version {v}",
    "Converts 2D PDF drawings into editable DXF files built with real CAD entities.":
        "Convertit des dessins PDF 2D en fichiers DXF modifiables, construits "
        "avec de vraies entités CAO.",
    "Created by {author}": "Créé par {author}",
    "Components": "Composants",
    "Everything runs on this computer. No drawing ever leaves it.":
        "Tout fonctionne sur cet ordinateur. Aucun dessin ne le quitte.",
    "Action": "Action", "Shortcut": "Raccourci",
    "Wheel": "Molette", "Middle button drag": "Glisser avec le bouton du milieu",
    "Space + drag": "Espace + glisser", "Escape": "Échap",
    "Zoom at the cursor": "Zoomer au curseur", "Pan the view": "Déplacer la vue",
    "Back to pan / cancel the tool": "Retour au déplacement / annuler l'outil",
    "Next / previous sheet": "Feuille suivante / précédente",
    "Toggle object snap": "Activer / désactiver l'accrochage",
    "An unexpected error occurred": "Une erreur inattendue s'est produite",
    "Details were written to {path}.": "Le détail a été écrit dans {path}.",
    "PDF drawings (*.pdf)": "Dessins PDF (*.pdf)",
    "DXF drawing (*.dxf)": "Dessin DXF (*.dxf)",
    "Text file (*.txt)": "Fichier texte (*.txt)",
    "HTML page (*.html)": "Page HTML (*.html)",
    "Choose a folder": "Choisir un dossier",
    "Scale 1:{den} read from the drawing. Check it with Measure before converting.":
        "Échelle 1:{den} lue sur le dessin. Vérifiez-la avec Mesurer avant "
        "de convertir.",
    "Scanned sheet detected: it will be traced and read with OCR.":
        "Feuille scannée détectée : elle sera vectorisée et lue par OCR.",
    "AutoCAD PDF detected: SHX text comments can be recovered (Settings > Text).":
        "PDF AutoCAD détecté : les commentaires de texte SHX peuvent être "
        "récupérés (Réglages > Texte).",
    "Next sheet": "Feuille suivante", "Previous sheet": "Feuille précédente",
    "AutoCAD 2018 and later": "AutoCAD 2018 et plus récent",
    "AutoCAD R12, legacy and CNC": "AutoCAD R12, ancien format et CNC",
    "Sheets {pages}: one file per sheet will be written next to this name.":
        "Feuilles {pages} : un fichier par feuille sera écrit à côté de ce nom.",
    # ---- report panel (core/report.py to_html with t=tr) ----
    "Success": "Réussite", "Cancelled": "Annulée", "entities": "entités",
    "Input": "Entrée", "Results": "Résultats", "Blocks": "Blocs",
    "Page notes": "Notes par feuille", "Warnings": "Avertissements",
    "Errors": "Erreurs", "Options": "Options", "none": "aucun",
    "in blocks": "dans les blocs", "Pages": "Feuilles", "of": "sur",
    "unknown producer": "producteur inconnu",
    "Verify the scale on a known distance, spot-check layer DIM and review layer DIM_RAW.":
        "Vérifiez l'échelle sur une distance connue, contrôlez le calque DIM "
        "et passez en revue le calque DIM_RAW.",
    "Lines": "Lignes", "Polylines": "Polylignes", "Arcs": "Arcs",
    "Circles": "Cercles", "Splines": "Splines", "Texts": "Textes",
    "Paragraphs (MTEXT)": "Paragraphes (MTEXT)",
    "SHX texts recovered": "Textes SHX récupérés", "OCR texts": "Textes OCR",
    "Hatches": "Hachures",
    "Dimensions (true DIMENSION)": "Cotes (vraies DIMENSION)",
    "Leaders": "Lignes de repère", "Blocks defined": "Blocs définis",
    "Block references (INSERT)": "Insertions de blocs (INSERT)",
    "Raster images": "Images raster",
    "Duplicate segments removed": "Segments en double supprimés",
    "White/background fills ignored": "Remplissages blancs / fonds ignorés",
    # ---- compact panel actions ----
    "Select sheets": "Sélection des feuilles", "Select all": "Tout sélectionner",
    "Select none": "Tout désélectionner",
    "Vector sheets only": "Feuilles vectorielles uniquement",
    "Scanned sheets only": "Feuilles scannées uniquement",
    "Invert selection": "Inverser la sélection",
    "Save HTML…": "HTML…", "Save the log as a text file":
        "Enregistrer le journal en fichier texte",
    "Save the report as an HTML page": "Enregistrer le rapport en page HTML",
    "Copy the log to the clipboard": "Copier le journal dans le presse-papiers",
    "Undo all layer changes": "Annuler toutes les modifications de calques",
    "Vector drawing: converted to exact CAD entities.":
        "Dessin vectoriel : converti en entités CAO exactes.",
    "Scanned sheet: traced and read with OCR.":
        "Feuille scannée : vectorisée et lue par OCR.",
    "No drawing content on this sheet.": "Aucun contenu dessiné sur cette feuille.",
    "Read the scale written on each sheet": "Lire l'échelle écrite sur chaque feuille",
    "landscape": "paysage", "portrait": "portrait",
    "Free software, GNU AGPL v3.0 — no activation required.":
        "Logiciel libre, GNU AGPL v3.0 — aucune activation requise.",
    "For sets whose sheets have different scales: each sheet uses the scale of its title block (1:100, 1/50…). The scale above is used when a sheet shows none, or several.":
        "Pour les jeux de feuilles à échelles différentes : chaque feuille "
        "utilise l'échelle de son cartouche (1:100, 1/50…). L'échelle "
        "ci-dessus sert quand une feuille n'en indique aucune, ou plusieurs.",
    "Not calibrated: each sheet uses the scale written on it, else the scale above.":
        "Non étalonné : chaque feuille utilise l'échelle écrite dessus, sinon "
        "l'échelle ci-dessus.",
    "Each sheet uses the scale of its title block (1:100, 1/50…); the drawing scale of the settings is used when a sheet shows none, or several.":
        "Chaque feuille utilise l'échelle de son cartouche (1:100, 1/50…) ; "
        "l'échelle des réglages sert quand une feuille n'en indique aucune, "
        "ou plusieurs.",
    "Uses the current settings. Calibration does not apply in this mode: check the scale of each sheet in its log.":
        "Utilise les réglages actuels. L'étalonnage ne s'applique pas dans ce "
        "mode : vérifiez l'échelle de chaque feuille dans son journal.",
    "{kept} of {total} layers kept": "{kept}/{total} gardés",
    # ---- engine progress messages (see tr_progress) ----
    "Page {pno}/{total}: {msg}": "Feuille {pno}/{total} : {msg}",
    "reading the PDF…": "lecture du PDF…",
    "rebuilding geometry…": "reconstruction de la géométrie…",
    "reconstructing dimensions and leaders…":
        "reconstruction des cotes et lignes de repère…",
    "detecting repeated symbols…": "détection des symboles répétés…",
    "writing DXF entities…": "écriture des entités DXF…",
    "scanned page — tracing at {dpi} dpi{ocr}…":
        "page scannée — vectorisation à {dpi} dpi{ocr}…",
    "Saving {name}…": "Enregistrement de {name}…", "Done.": "Terminé.",
})

# ---- version 1.0: area, overlay, DWG, OCR engines, rebuilt patterns ----
_fr({
    "Output folder": "Dossier de sortie",
    "Uses the current settings (files saved as {fmt}). Calibration and area do not apply in this mode: check the scale of each sheet in its log.":
        "Utilise les réglages actuels (fichiers enregistrés en {fmt}). "
        "L'étalonnage et la zone ne s'appliquent pas dans ce mode : "
        "vérifiez l'échelle de chaque feuille dans son journal.",
    "DXF drawing": "Dessin DXF",
    "DWG drawing (AutoCAD 2000 format)": "Dessin DWG (format AutoCAD 2000)",
    "DWG drawing, AutoCAD 2000 format (*.dwg)":
        "Dessin DWG, format AutoCAD 2000 (*.dwg)",
    "Save the drawing…": "Enregistrer le dessin…",
    "Save DWG…": "Enregistrer en DWG…",
    "Save the reviewed drawing (Ctrl+S)":
        "Enregistrer le dessin vérifié (Ctrl+S)",
    "DWG output is not available: the LibreDWG converter (dxf2dwg) was not found next to ConvertCAD. Save as DXF, or reinstall ConvertCAD.":
        "La sortie DWG n'est pas disponible : le convertisseur LibreDWG "
        "(dxf2dwg) est introuvable à côté de ConvertCAD. Enregistrez en DXF "
        "ou réinstallez ConvertCAD.",
    "A DWG needs AutoCAD 2000 entities (classic leaders, colour index...). ConvertCAD converts the drawing once more for the DWG, then saves it. Continue?":
        "Un DWG demande des entités AutoCAD 2000 (lignes de repère "
        "classiques, couleurs indexées…). ConvertCAD convertit le dessin une "
        "nouvelle fois pour le DWG, puis l'enregistre. Continuer ?",
    "Writing the DWG…": "Écriture du DWG…",
    "Could not save the drawing: {err}":
        "Impossible d'enregistrer le dessin : {err}",
    "Overlay PDF": "Superposer le PDF",
    "Overlay the PDF on the DXF": "Superposer le PDF au DXF",
    "Show the PDF sheet under the DXF result to check the conversion (O)":
        "Afficher la feuille PDF sous le résultat DXF pour contrôler la "
        "conversion (O)",
    "Opacity of the PDF under the DXF": "Opacité du PDF sous le DXF",
    "Overlay: the PDF is shown under the DXF. Lines that do not match stand out.":
        "Superposition : le PDF est affiché sous le DXF. Les traits qui ne "
        "coïncident pas ressortent.",
    "Select area": "Sélectionner une zone",
    "Select area…": "Sélectionner une zone…",
    "Drag a rectangle on the sheet: only that part is converted (A)":
        "Tracez un rectangle sur la feuille : seule cette partie est "
        "convertie (A)",
    "Select area: drag a rectangle around the part to convert.":
        "Sélection de zone : tracez un rectangle autour de la partie à "
        "convertir.",
    "Area": "Zone",
    "Area selected: {size}. Only this part of the sheet will be converted.":
        "Zone sélectionnée : {size}. Seule cette partie de la feuille sera "
        "convertie.",
    "Whole sheet": "Feuille entière",
    "Convert the whole sheet": "Convertir la feuille entière",
    "Convert the whole sheet again": "Convertir de nouveau la feuille entière",
    "Whole sheet: the area selection was removed.":
        "Feuille entière : la sélection de zone a été retirée.",
    "Area: {size} — only this part of each sheet is converted.":
        "Zone : {size} — seule cette partie de chaque feuille est convertie.",
    "Area: whole sheet.": "Zone : feuille entière.",
    "Scale, units and area": "Échelle, unités et zone",
    "Converted in {s} s: {n} entities on {l} layers. Review the result, then save it.":
        "Converti en {s} s : {n} entités sur {l} calques. Vérifiez le "
        "résultat, puis enregistrez-le.",
    "Rebuild hatch patterns": "Reconstruire les motifs de hachure",
    "CAD programs print hatches as hundreds of parallel lines: they become one pattern HATCH (angle and spacing measured).":
        "Les logiciels de CAO impriment les hachures en centaines de traits "
        "parallèles : ils redeviennent une HATCH à motif (angle et "
        "espacement mesurés).",
    "Rebuild dashed lines": "Reconstruire les lignes pointillées",
    "CAD programs print axes and hidden lines as separate dashes: they become one line with its linetype (dash lengths measured).":
        "Les logiciels de CAO impriment les axes et lignes cachées en tirets "
        "séparés : ils redeviennent une ligne avec son type de ligne "
        "(longueurs des tirets mesurées).",
    "Ignore white masks, white lines and page backgrounds":
        "Ignorer masques blancs, traits blancs et fonds de page",
    "White elements are invisible on the PDF sheet; in CAD they would show or hide the drawing. Hatches keep a hole under the white text masks.":
        "Les éléments blancs sont invisibles sur la feuille PDF ; en CAO ils "
        "apparaîtraient ou masqueraient le dessin. Les hachures gardent un "
        "trou sous les masques blancs des textes.",
    "Recover text drawn as strokes or outlines":
        "Récupérer les textes dessinés en traits ou en contours",
    "AutoCAD prints SHX and TrueType text as lines or filled outlines and hides the real text in the PDF. The real text is used (layer TEXT_SHX); the strokes go to layer TEXT_SHX_STROKES, switched off.":
        "AutoCAD imprime les textes SHX et TrueType en traits ou contours "
        "remplis et cache le vrai texte dans le PDF. Le vrai texte est "
        "utilisé (calque TEXT_SHX) ; les traits vont sur le calque "
        "TEXT_SHX_STROKES, désactivé.",
    "Also match rotated and mirrored copies":
        "Reconnaître aussi les copies tournées et en miroir",
    "A symbol turned by 90, 180 or 270 degrees, or mirrored, uses the same block (insertion with rotation / mirroring).":
        "Un symbole tourné de 90, 180 ou 270 degrés, ou en miroir, utilise "
        "le même bloc (insertion avec rotation / miroir).",
    "Text on scanned pages is recognised by an OCR engine.":
        "Le texte des pages scannées est reconnu par un moteur OCR.",
    "Fast: Tesseract. Accurate: RapidOCR (PaddleOCR models, better on drawings). Maximum: PaddleOCR's largest models. Automatic: the best one installed.":
        "Rapide : Tesseract. Précis : RapidOCR (modèles PaddleOCR, meilleur "
        "sur les plans). Maximum : les plus grands modèles PaddleOCR. "
        "Automatique : le meilleur installé.",
    "OCR engine": "Moteur OCR",
    "Automatic (best available)": "Automatique (le meilleur disponible)",
    "Fast — Tesseract": "Rapide — Tesseract",
    "Accurate — RapidOCR": "Précis — RapidOCR",
    "Maximum — PaddleOCR": "Maximum — PaddleOCR",
    "(not installed)": "(non installé)",
    "OCR ready: {engines}": "OCR prêt : {engines}",
    "OCR not available: no OCR engine was found. Tracing still works.":
        "OCR indisponible : aucun moteur OCR trouvé. La vectorisation "
        "fonctionne quand même.",
    "File format": "Format de fichier",
    "DWG files are written by the free GNU LibreDWG converter included with ConvertCAD, in the AutoCAD 2000 format that every AutoCAD version opens.":
        "Les fichiers DWG sont écrits par le convertisseur libre GNU "
        "LibreDWG inclus dans ConvertCAD, au format AutoCAD 2000 que toutes "
        "les versions d'AutoCAD ouvrent.",
    "DWG files are always written in the AutoCAD 2000 format.":
        "Les fichiers DWG sont toujours écrits au format AutoCAD 2000.",
    # report rows (core/report.py)
    "Hatch patterns rebuilt": "Motifs de hachure reconstruits",
    "Dashed lines rebuilt": "Lignes pointillées reconstruites",
    "Dash pieces merged": "Tirets fusionnés",
})
