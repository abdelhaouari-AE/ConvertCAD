# OCR for scanned PDFs

ConvertCAD traces the lines and circles of scanned drawings on its own. To also **read the text** of a scan, it uses an OCR engine. Choose it in *Settings > Scanned pages > OCR engine*:

| Engine | What it is | Best for |
|---|---|---|
| **Automatic** (default) | the best engine installed | most users |
| **Fast — Tesseract** | the classic open-source OCR program | clean typed text, quick checks |
| **Accurate — RapidOCR** | PaddleOCR's PP-OCR models, run by ONNX Runtime | drawings: whole text lines, small, rotated and vertical text |
| **Maximum — PaddleOCR** | the larger PP-OCR models | difficult scans (low quality, dense title blocks) — slower |

On drawings, *Accurate* reads far better than *Fast*: Tesseract is tuned for pages of prose, the PP-OCR models find text lines anywhere, at any angle, even crossed by lines. An engine that is not installed is marked *(not installed)*; the report always says which engine was used.

**The downloads of ConvertCAD already include the engines** (Windows: all three; Linux: *Accurate* and *Maximum*, plus Tesseract from the system). Nothing to install. The sections below are for running from the source code or adding languages.

## Tesseract ("Fast")

- **Windows, installed**: download the installer published by the University of Mannheim (search for **"Tesseract UB Mannheim"**) and tick the extra languages you need (**French**, **Arabic**). ConvertCAD looks in `C:\Program Files\Tesseract-OCR`, in your user programs folder and on the system PATH.
- **Windows, portable**: copy a whole `Tesseract-OCR` folder, rename it **`tesseract`** and place it **next to ConvertCAD.exe** (with `tesseract.exe` and `tessdata\eng.traineddata`, `fra.traineddata`, `ara.traineddata`).
- **Linux**: `sudo apt install tesseract-ocr tesseract-ocr-fra tesseract-ocr-ara`.

## RapidOCR ("Accurate") and PaddleOCR ("Maximum") from source

- *Accurate* comes with the Python packages (`pip install -r requirements.txt`): `rapidocr` and `onnxruntime`, models included.
- *Maximum* uses the larger models: run `python scripts/get_ocr_models.py` once (it also gets the Arabic model). Alternatively, install the full PaddleOCR library: `pip install -r requirements-paddle.txt` (about 1 GB; it downloads its own models the first time it is used — the only case where ConvertCAD's OCR goes online).

## Languages

Choose the language in *Settings > Scanned pages*: `eng+fra` (default), `fra`, `eng`, `eng+fra+ara` or `ara`. Tesseract needs the `.traineddata` file of each language. The PP-OCR models read Latin-script languages (English, French…) together; Arabic uses its own model (included in the downloads) and is written in the normal reading order.

## Tips

- 300 dpi is a good default. Use 400–600 dpi for small text on large sheets (slower).
- *Also read vertical text* adds a second Tesseract pass for texts written bottom-to-top; the PP-OCR engines read vertical text without it.
- When a scanned PDF is already searchable (it contains a text layer), ConvertCAD uses that text instead of OCR.
