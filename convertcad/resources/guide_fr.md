# Guide d'utilisation de ConvertCAD

ConvertCAD transforme des dessins PDF 2D en **fichiers DXF ou DWG modifiables, construits avec de vraies entités CAO** : lignes, polylignes, arcs, cercles, splines, hachures, textes et paragraphes, vraies cotes, lignes de repère, calques et blocs — et non un enchevêtrement de traits éclatés. Tout s'exécute sur votre ordinateur.

## Les quatre étapes

1. **Ouvrir un dessin** — *Ouvrir un PDF…* (Ctrl+O), glisser un PDF sur la fenêtre, ou essayer le plan d'exemple. Chaque feuille apparaît à gauche avec un badge : **Vectoriel** (idéal), **Scan** (sera vectorisé et lu par OCR) ou **Vide**. Décochez les feuilles à ne pas convertir ; le menu de sélection de l'en-tête *Feuilles* sélectionne tout, rien, seulement les feuilles vectorielles ou seulement les scannées.
2. **Vérifier l'échelle** — choisissez l'échelle dans *Réglages > Échelle, unités et zone* (ConvertCAD la lit dans le cartouche quand il le peut). Pour un résultat exact, utilisez **Étalonner** (C) : cliquez deux points dont vous connaissez la distance réelle — par exemple deux axes — puis saisissez la distance. **Mesurer** (M) permet de vérifier toute distance avant de convertir. Pour ne convertir qu'une partie de la feuille, utilisez **Sélectionner une zone** (A) et tracez un rectangle ; *Feuille entière* l'annule.
3. **Convertir** (Ctrl+Entrée) — s'exécute en arrière-plan ; vous pouvez continuer à zoomer ou annuler à tout moment.
4. **Vérifier et enregistrer** — l'onglet *Résultat DXF* montre le dessin converti tel que le lira le logiciel de CAO. **Superposer le PDF** (O) affiche le PDF dessous, avec un curseur d'opacité : toute différence se voit aussitôt. Dans *Calques*, décochez les calques inutiles, renommez-les (double-clic) ou changez leur couleur (clic sur la pastille) ; le bouton ↺ annule toutes les modifications de calques. Le *Rapport* liste tout ce qui a été créé, avec les avertissements. Puis **Enregistrer le DXF…** (Ctrl+S) — ou **Enregistrer en DWG…** : choisissez le type DWG dans la fenêtre d'enregistrement, ou réglez *Réglages > Sortie > Format de fichier* sur DWG avant de convertir.

## Naviguer dans le dessin

| Action | Comment |
|---|---|
| Zoomer au curseur | Molette |
| Déplacer la vue | Glisser avec le bouton du milieu, Espace + glisser, ou glisser avec l'outil Déplacer |
| Ajuster la feuille | F |
| Feuille suivante / précédente | Page suiv. / Page préc. |
| Annuler un outil | Échap (clic droit annule le premier point) |

La feuille reste nette à tout niveau de zoom : la zone visible est redessinée à la résolution de l'écran.

## Accrochage aux objets

Pendant une mesure ou un étalonnage, les clics se calent sur le point exact du dessin, comme l'accrochage d'AutoCAD. La barre d'état active chaque mode :

- **EXT** — extrémités et coins (carré)
- **MIL** — milieux des segments (triangle)
- **INT** — intersections (croix)
- **CEN** — centres des cercles et arcs (cercle)

F3 active ou désactive l'accrochage.

## Ce que produit la conversion

| Dans le PDF | Dans le DXF |
|---|---|
| Courbes circulaires | Vrais **ARCS** et **CERCLES** |
| Courbes en plusieurs morceaux | Une **SPLINE** exacte |
| Segments jointifs | Une **LWPOLYLINE** (fermée si elle boucle) |
| Motifs de tirets, ou tirets dessinés en morceaux séparés | Une ligne avec un type de ligne **CENTER**, **DASHED**, **DASHDOT**, **PHANTOM**… mesuré sur le PDF |
| Zones remplies | **HACHURE** pleine sur le calque HATCH |
| Hachures dessinées en nombreuses lignes parallèles | Une **HACHURE** à motif (angle et espacement du PDF) |
| Texte | **TEXTE** ; les lignes empilées deviennent un paragraphe **MTEXT** |
| Texte SHX AutoCAD dessiné en traits | Vrai **TEXTE** sur le calque TEXT_SHX (les traits restent sur le calque masqué TEXT_SHX_STROKES) |
| Flèche + ligne + flèche + valeur | Vraie **COTE** (calque DIM) — la valeur garde le texte du PDF |
| Traits obliques + ligne + valeur | Vraie **COTE** à traits architecturaux |
| Flèche + ligne + note | **LIGNE DE REPÈRE** / repère multiple (calque ANNOT_LEADER) |
| Symboles identiques répétés, même tournés ou en miroir | Un **BLOC** + une insertion par occurrence |
| Images incorporées, scans | Image sur le calque verrouillé IMG_RASTER |

Les textes de mesure non associés à une cote sont placés sur le calque **DIM_RAW** (rouge) pour vérification. Rien n'est inventé.

## Les réglages

**Échelle, unités et zone** — échelle du dessin (1:N) et unité du DXF (mm, cm, m) ; *Sélectionner une zone… / Feuille entière* (seule la zone est convertie, dans les coordonnées de la feuille ; la zone s'applique à chaque feuille convertie). *Lire l'échelle écrite sur chaque feuille* sert aux jeux de feuilles à échelles différentes (plan au 1:100, détails au 1:20) : chaque feuille utilise l'échelle de son cartouche, et l'échelle ci-dessus sert quand une feuille n'en indique aucune ou plusieurs ; le rapport indique l'échelle retenue pour chaque feuille. L'étalonnage remplace les deux ; le panneau affiche l'échelle équivalente (« environ 1:100,2 ») comme contrôle.

**Géométrie** — reconstruire arcs et cercles ; joindre les segments en polylignes ; joindre les courbes en splines uniques ; *précision des courbes* (Fine / Normale / Large) ; remplissages en hachures pleines ; *reconstruire les motifs de hachure* (lignes parallèles → HACHURE à motif) ; *reconstruire les lignes pointillées* (tirets séparés → une ligne avec un type de ligne) ; ignorer masques blancs, traits blancs et fonds de page (ils masqueraient le dessin dans la CAO).

**Texte** — exporter le texte ; regrouper les lignes empilées en paragraphes MTEXT ; *rapport de hauteur* (hauteur des majuscules ÷ taille de police, 0,70 convient à la plupart des polices) ; *récupérer les textes dessinés en traits ou en contours* : le texte SHX AutoCAD redevient du vrai texte (calque TEXT_SHX) grâce aux commentaires cachés qu'AutoCAD ajoute à ses PDF, et le texte TrueType dessiné en contours remplis est remplacé par son vrai texte.

**Cotes et lignes de repère** — reconstruire les cotes à flèches et/ou à traits obliques ; reconstruire les lignes de repère.

**Calques et blocs** — conserver les calques du PDF s'il en a ; *nom des calques* sinon : couleur + épaisseur + type de ligne (ex. GEO_BLACK_050_CENTER), couleur seule, ou un seul calque ; reconnaître les types de ligne ; *couleurs* : index de couleur AutoCAD (compatible avec les styles de tracé CTB) ou couleur vraie (RVB exact) ; détecter les symboles répétés comme blocs, avec un nombre minimal d'occurrences, et *reconnaître aussi les copies tournées et en miroir*.

**Pages scannées** — vectoriser lignes et cercles ; lire le texte par OCR (modèles PP-OCR, sur cet ordinateur) ; *langues OCR* : anglais, français… (alphabet latin, intégré), un autre alphabet (arabe, cyrillique, grec…) ou les deux pour les plans mixtes — seules les langues installées sont proposées ; *précision de l'OCR* : standard (modèle intégré) ou maximale (modèles plus grands, plus lents) ; **Langues et modèles OCR…** télécharge les autres langues et les modèles de précision maximale, ou les installe depuis des fichiers sur un ordinateur sans internet (voir *Aide > Guide de l'OCR*) ; résolution de lecture (200 à 600 dpi) ; utiliser la couche texte du PDF quand le scan est déjà indexé ; conserver les images sur un calque verrouillé.

**Sortie** — *format de fichier* : DXF, ou DWG (format AutoCAD 2000 : s'ouvre dans tous les AutoCAD depuis 2000 et tous les logiciels de CAO actuels ; écrit par le convertisseur GNU LibreDWG inclus et contrôlé après écriture) ; version DXF (R2018 pour les logiciels récents, R12 pour les anciennes machines CNC) ; avec plusieurs feuilles, un DXF côte à côte ou un DXF par feuille ; écrire un journal de conversion à côté du DXF ; ouvrir le dossier après l'enregistrement.

**Préréglages** — Recommandé, Plans d'architecture, Plans de structure / coffrage, Plans d'archive scannés, Géométrie seule, CNC / laser. *Enregistrer comme préréglage…* conserve vos propres combinaisons.

## Convertir un dossier entier

*Convertir un dossier…* (Ctrl+B) convertit chaque PDF d'un dossier (sous-dossiers en option) avec les réglages actuels. Chaque fichier obtient son DXF (ou DWG) et son journal dans le dossier de sortie. L'étalonnage ne s'applique pas dans ce mode : par défaut chaque feuille utilise l'échelle écrite dans son cartouche, sinon l'échelle des réglages — vérifiez-la dans chaque journal.

Les mêmes conversions peuvent être automatisées avec le programme console *ConvertCAD-cli.exe* (à côté de ConvertCAD.exe) — tapez `ConvertCAD-cli --help` dans une invite de commandes.

## Contrôle après chaque conversion

1. Mesurez une distance connue dans la CAO pour confirmer l'échelle.
2. N'affichez que le calque DIM et vérifiez quelques valeurs par rapport au PDF.
3. Passez en revue le calque DIM_RAW.
4. Lisez les avertissements du rapport.

## Dépannage

- **Le texte arrive en petits traits** — le PDF utilise des polices SHX sans les commentaires cachés (PDF non produit par AutoCAD, ou exporté sans eux) : les traits restent de la géométrie. Pour les PDF AutoCAD, laissez *Récupérer les textes dessinés en traits ou en contours* activé.
- **Une zone blanche masque le dessin dans la CAO** — laissez *Ignorer masques blancs, traits blancs et fonds de page* activé.
- **L'OCR est médiocre** — vérifiez les *langues OCR* (un plan en cyrillique ou en arabe demande son alphabet : *Langues et modèles OCR…*) ; pour les scans médiocres ou les petits textes, choisissez *Précision de l'OCR : maximale* ou une résolution plus élevée ; voir *Aide > Guide de l'OCR*.
- **Un téléchargement OCR échoue** — vérifiez la connexion internet ou le proxy de l'entreprise ; sur un ordinateur sans internet, utilisez *Installer depuis un fichier…* (voir *Aide > Guide de l'OCR*).
- **Le DWG n'a pas pu être écrit** — le rapport indique pourquoi, et le dessin est enregistré en DXF à la place ; envoyez le PDF et le journal si cela se reproduit.
- **Trop de petits calques** — choisissez *Couleur seule* ou *Un seul calque*, ou décochez des calques avant d'enregistrer.
- **Un symbole répété n'est pas devenu un bloc** — les copies tournées d'un angle autre que 90°/180°/270° sont des symboles différents ; baissez *Occurrences minimales* s'il n'apparaît que deux fois.
- **Une conversion est lente** — très grands scans : baissez la résolution de lecture.

ConvertCAD {APP_VERSION} — © {APP_YEAR} {APP_AUTHOR}
