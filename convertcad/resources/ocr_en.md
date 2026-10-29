# OCR for scanned PDFs

ConvertCAD traces the lines and circles of scanned drawings and **reads their text** with PaddleOCR's **PP-OCR** models, run on this computer by RapidOCR and ONNX Runtime. They find whole text lines anywhere on the sheet — small, rotated, vertical or crossed by lines. No drawing ever leaves the computer.

## Languages

Choose them in *Settings > Scanned pages > OCR languages*:

| Choice | Reads | Model |
|---|---|---|
| **English, French… (Latin script)** — default | English, French, Spanish, German, Italian, Portuguese, Dutch, Polish, Turkish, Vietnamese and 37 other Latin-script languages; also Chinese and Japanese | **built in** (about 30 MB) |
| **Arabic**, **Cyrillic**, **Greek**, **Korean**, **Devanagari**, **Thai**, **Tamil**, **Telugu** | that script (Arabic also reads Persian and Urdu; Cyrillic reads Russian, Ukrainian, Bulgarian, Serbian…) | download |
| **English, French… + Arabic** (or another script) | drawings that mix both, e.g. a French plan with an Arabic title block: each line keeps the reading of its own script | built in + download |

Only the installed languages are listed. A choice whose model is missing (settings copied from another computer, model removed) stays visible, marked *(not downloaded)*: the built-in model is used instead, and the report says so.

## Accuracy

- **Standard** (default) — the built-in model: fast, and the right choice for almost every drawing.
- **Maximum** — larger models (download, 132 MB): slightly better on poor scans, but about 20 times slower (measured: 83 % of the labels of a test sheet read instead of 81 %). It applies to the Latin-script languages; the other scripts have one model each.

## Downloading languages and models

*Settings > Scanned pages > OCR languages and models…* (also in the *Tools* menu):

1. Choose a model in the list (its size is shown), then **Download**. A progress bar follows the download; **Cancel** stops it.
2. Every file is checked (SHA-256) before it is kept: an interrupted or damaged download never leaves a bad model behind.
3. The model then works **offline, for good**. **Remove** deletes it.

Where the models are stored:

| ConvertCAD | Folder |
|---|---|
| Windows (installer or portable zip) | `%LOCALAPPDATA%\ConvertCAD\ocr_models` |
| Linux (AppImage, .deb, tar.gz) | `~/.local/share/convertcad/ocr_models` |
| Portable mode (an empty file `ConvertCAD.portable` next to the program) | the `ocr_models` folder next to the program: the models travel with it |

The environment variable `CONVERTCAD_OCR_MODELS` can choose another folder. Uninstalling ConvertCAD on Windows removes the downloaded models; updating it keeps them.

**Where they come from:** ConvertCAD's GitHub release `ocr-models-v1`, otherwise RapidOCR's model repository (ModelScope). Only the requested file is downloaded; nothing is sent, neither drawings nor information about you. A company proxy is used automatically when it is set for the system (or in the `HTTPS_PROXY` variable).

**Computer without internet:** on another computer, open the download page (button *Download page*), download the `.onnx` files of the model, copy them (USB stick…), then click **Install from file…** — the files are recognised by their checksum, whatever their name.

**Command line:** `ConvertCAD-cli --list-ocr` lists the models, `ConvertCAD-cli --get-ocr-model arabic latin_max` downloads them, then `--ocr-lang latin+arabic --ocr-quality maximum` uses them.

## Tips

- 300 dpi is a good default. Use 400–600 dpi for small text on large sheets (slower).
- Vertical text is read without any extra setting.
- When a scanned PDF is already searchable (it contains a text layer), ConvertCAD uses that text instead of OCR.
- Running from the source code: `pip install -r requirements.txt` installs RapidOCR, ONNX Runtime and the built-in model.
