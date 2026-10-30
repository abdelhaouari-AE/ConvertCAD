# OCR des PDF scannés

ConvertCAD vectorise les lignes, cercles et arcs des plans scannés et **lit leur texte** avec les modèles **PP-OCR** de PaddleOCR, exécutés sur cet ordinateur par RapidOCR et ONNX Runtime. Ils trouvent les lignes de texte entières partout sur la feuille — petites, inclinées, verticales ou traversées par des traits. Aucun plan ne quitte l'ordinateur.

## Langues

Choisissez-les dans *Réglages > Pages scannées > Langues OCR* :

| Choix | Lit | Modèle |
|---|---|---|
| **Anglais, français… (alphabet latin)** — par défaut | anglais, français, espagnol, allemand, italien, portugais, néerlandais, polonais, turc, vietnamien et 37 autres langues en alphabet latin ; aussi le chinois et le japonais | **intégré** (environ 30 Mo) |
| **Arabe**, **Cyrillique**, **Grec**, **Coréen**, **Dévanagari**, **Thaï**, **Tamoul**, **Télougou** | cet alphabet (l'arabe lit aussi le persan et l'ourdou ; le cyrillique lit le russe, l'ukrainien, le bulgare, le serbe…) | à télécharger |
| **Anglais, français… + Arabe** (ou un autre alphabet) | les plans qui mélangent les deux, par ex. un plan en français avec un cartouche en arabe : chaque ligne garde la lecture de son propre alphabet | intégré + à télécharger |

Seules les langues installées sont proposées. Un choix dont le modèle manque (réglages copiés d'un autre ordinateur, modèle supprimé) reste visible, marqué *(non téléchargé)* : le modèle intégré est alors utilisé, et le rapport l'indique.

## Précision

- **Standard** (par défaut) — le modèle intégré : rapide, et le bon choix pour presque tous les plans.
- **Maximale** — des modèles plus grands (à télécharger, 132 Mo) : un peu meilleurs sur les scans médiocres, mais environ 20 fois plus lents (mesuré : 83 % des textes d'une feuille d'essai lus au lieu de 81 %). Elle concerne les langues en alphabet latin ; les autres alphabets ont un seul modèle chacun.

## Télécharger des langues et des modèles

*Réglages > Pages scannées > Langues et modèles OCR…* (aussi dans le menu *Outils*) :

1. Choisissez un modèle dans la liste (sa taille est indiquée), puis **Télécharger**. Une barre de progression suit le téléchargement ; **Annuler** l'arrête.
2. Chaque fichier est vérifié (SHA-256) avant d'être conservé : un téléchargement interrompu ou abîmé ne laisse jamais de modèle défectueux.
3. Le modèle fonctionne ensuite **hors ligne, définitivement**. **Supprimer** l'efface.

Emplacement des modèles :

| ConvertCAD | Dossier |
|---|---|
| Windows (installateur ou zip portable) | `%LOCALAPPDATA%\ConvertCAD\ocr_models` |
| Linux (AppImage, .deb, tar.gz) | `~/.local/share/convertcad/ocr_models` |
| Mode portable (un fichier vide `ConvertCAD.portable` à côté du programme) | le dossier `ocr_models` à côté du programme : les modèles voyagent avec lui |

La variable d'environnement `CONVERTCAD_OCR_MODELS` permet de choisir un autre dossier. La désinstallation de ConvertCAD sous Windows supprime les modèles téléchargés ; une mise à jour les conserve.

**Provenance :** la publication GitHub `ocr-models-v1` de ConvertCAD, sinon le dépôt de modèles de RapidOCR (ModelScope). Seul le fichier demandé est téléchargé ; rien n'est envoyé, ni plan ni information sur vous. Le proxy de l'entreprise est utilisé automatiquement lorsqu'il est réglé pour le système (ou dans la variable `HTTPS_PROXY`).

**Ordinateur sans internet :** sur un autre ordinateur, ouvrez la page de téléchargement (bouton *Page de téléchargement*), téléchargez les fichiers `.onnx` du modèle, copiez-les (clé USB…), puis cliquez sur **Installer depuis un fichier…** — les fichiers sont reconnus par leur empreinte, quel que soit leur nom.

**Ligne de commande :** `ConvertCAD-cli --list-ocr` liste les modèles, `ConvertCAD-cli --get-ocr-model arabic latin_max` les télécharge, puis `--ocr-lang latin+arabic --ocr-quality maximum` les utilise.

## Conseils

- 300 dpi est un bon choix par défaut. Passez à 400–600 dpi pour les petits textes sur grandes feuilles (plus lent).
- Le texte vertical est lu sans réglage particulier.
- Quand un PDF scanné est déjà « interrogeable » (il contient une couche texte), ConvertCAD utilise ce texte au lieu de l'OCR.
- Depuis le code source : `pip install -r requirements.txt` installe RapidOCR, ONNX Runtime et le modèle intégré.
