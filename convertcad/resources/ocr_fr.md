# OCR des PDF scannés

ConvertCAD vectorise seul les lignes et cercles des plans scannés. Pour **lire aussi le texte** d'un scan, il utilise un moteur d'OCR. Choisissez-le dans *Réglages > Pages scannées > Moteur OCR* :

| Moteur | Ce que c'est | Idéal pour |
|---|---|---|
| **Automatique** (par défaut) | le meilleur moteur installé | la plupart des utilisateurs |
| **Rapide — Tesseract** | le programme d'OCR libre classique | texte dactylographié net, vérifications rapides |
| **Précis — RapidOCR** | les modèles PP-OCR de PaddleOCR, exécutés par ONNX Runtime | les plans : lignes de texte entières, petits textes, textes inclinés et verticaux |
| **Maximum — PaddleOCR** | les modèles PP-OCR de plus grande taille | les scans difficiles (mauvaise qualité, cartouches denses) — plus lent |

Sur les plans, *Précis* lit bien mieux que *Rapide* : Tesseract est conçu pour des pages de texte courant, les modèles PP-OCR trouvent les lignes de texte partout, sous tous les angles, même traversées par des traits. Un moteur absent est marqué *(non installé)* ; le rapport indique toujours le moteur utilisé.

**Les téléchargements de ConvertCAD incluent déjà les moteurs** (Windows : les trois ; Linux : *Précis* et *Maximum*, plus Tesseract du système). Rien à installer. Les sections suivantes concernent l'exécution depuis le code source ou l'ajout de langues.

## Tesseract (« Rapide »)

- **Windows, installé** : téléchargez l'installateur publié par l'Université de Mannheim (recherchez **« Tesseract UB Mannheim »**) et cochez les langues utiles (**français**, **arabe**). ConvertCAD cherche dans `C:\Program Files\Tesseract-OCR`, dans le dossier des programmes de l'utilisateur et dans le PATH du système.
- **Windows, portable** : copiez un dossier `Tesseract-OCR` complet, renommez-le **`tesseract`** et placez-le **à côté de ConvertCAD.exe** (avec `tesseract.exe` et `tessdata\eng.traineddata`, `fra.traineddata`, `ara.traineddata`).
- **Linux** : `sudo apt install tesseract-ocr tesseract-ocr-fra tesseract-ocr-ara`.

## RapidOCR (« Précis ») et PaddleOCR (« Maximum ») depuis le code source

- *Précis* est fourni avec les bibliothèques Python (`pip install -r requirements.txt`) : `rapidocr` et `onnxruntime`, modèles inclus.
- *Maximum* utilise les grands modèles : lancez une fois `python scripts/get_ocr_models.py` (il récupère aussi le modèle arabe). Autre possibilité : installer la bibliothèque PaddleOCR complète, `pip install -r requirements-paddle.txt` (environ 1 Go ; elle télécharge ses propres modèles à sa première utilisation — le seul cas où l'OCR de ConvertCAD va sur Internet).

## Langues

Choisissez la langue dans *Réglages > Pages scannées* : `eng+fra` (par défaut), `fra`, `eng`, `eng+fra+ara` ou `ara`. Tesseract a besoin du fichier `.traineddata` de chaque langue. Les modèles PP-OCR lisent ensemble les langues en alphabet latin (anglais, français…) ; l'arabe utilise son propre modèle (inclus dans les téléchargements) et il est écrit dans l'ordre normal de lecture.

## Conseils

- 300 dpi est un bon réglage par défaut. Utilisez 400 à 600 dpi pour les petits textes sur grandes feuilles (plus lent).
- *Lire aussi le texte vertical* ajoute une seconde passe Tesseract pour les textes écrits de bas en haut ; les moteurs PP-OCR lisent le texte vertical sans elle.
- Quand un PDF scanné est déjà indexé (il contient une couche texte), ConvertCAD utilise ce texte au lieu de l'OCR.
