# Third-party notices

ConvertCAD — Copyright © 2026 abdelhaouari — is released under the GNU Affero
General Public License v3.0 (see `LICENSE`).

ConvertCAD uses the open-source components below. The programs we distribute — the
Windows portable zip and installer, the Linux tar.gz, AppImage and .deb — include the
ones marked **bundled**. Their licence texts are in their own package folders inside
`_internal` (`*.dist-info`, `libredwg/COPYING`) and on the websites listed.

| Component | Used for | Licence | Distribution | Website |
|---|---|---|---|---|
| Python | language runtime | PSF License 2.0 | bundled | <https://www.python.org/> |
| Qt 6 / PySide6-Essentials, Shiboken6 | desktop interface | LGPL-3.0 (also GPL-2.0/3.0) | bundled, the Qt libraries are separate, replaceable files | <https://www.qt.io/>, <https://doc.qt.io/qtforpython/> |
| PyMuPDF / MuPDF (Artifex) | PDF reading and rendering | AGPL-3.0, or Artifex commercial licence | bundled | <https://pymupdf.readthedocs.io/>, <https://artifex.com/> |
| ezdxf (Manfred Moitzi) | DXF writing and DXF preview | MIT | bundled | <https://ezdxf.mozman.at/> |
| fontTools, pyparsing, typing_extensions | ezdxf dependencies | MIT, MIT, PSF | bundled | <https://github.com/fonttools/fonttools>, <https://github.com/pyparsing/pyparsing> |
| NumPy | numerical computing | BSD-3-Clause (and bundled BSD/MIT/zlib parts) | bundled | <https://numpy.org/> |
| OpenCV (opencv-python-headless) | scanned-page tracing | Apache-2.0 (OpenCV); MIT (Python packaging) | bundled | <https://opencv.org/>, <https://github.com/opencv/opencv-python> |
| **GNU LibreDWG** 0.13.4, with 3 ConvertCAD patches | DWG output (`dxf2dwg`, `dwg2dxf` programs) | **GPL-3.0-or-later** | bundled (`libredwg` folder: programs, `COPYING`, `SOURCE.txt`) | <https://www.gnu.org/software/libredwg/> |
| libssp (GCC runtime) | used by the Windows LibreDWG programs | GPL-3.0 with the GCC Runtime Library Exception | bundled (Windows) | <https://gcc.gnu.org/> |
| RapidOCR (RapidAI) | OCR of scanned pages | Apache-2.0 | bundled | <https://github.com/RapidAI/RapidOCR> |
| PP-OCR models (PaddleOCR, Baidu), ONNX format as published by RapidOCR | text detection / recognition: the built-in model (PP-OCRv6 small: Latin-script languages, Chinese, Japanese); the maximum accuracy models (PP-OCRv6 medium) and the script models (PP-OCRv5: Arabic, Cyrillic, Greek, Korean, Devanagari, Thai, Tamil, Telugu) | Apache-2.0 | built-in model bundled (`rapidocr/models`); the others downloaded by the user from the program (release `ocr-models-v1` of this repository, or RapidOCR's model repository) | <https://github.com/PaddlePaddle/PaddleOCR> |
| ONNX Runtime (Microsoft) | runs the OCR models | MIT | bundled | <https://onnxruntime.ai/> |
| flatbuffers, protobuf | ONNX Runtime dependencies | Apache-2.0, BSD-3-Clause | bundled | <https://github.com/google/flatbuffers>, <https://github.com/protocolbuffers/protobuf> |
| Shapely (+ GEOS), pyclipper (+ Clipper) | RapidOCR dependencies (text box geometry) | BSD-3-Clause (GEOS: LGPL-2.1); MIT (Clipper: Boost Software License 1.0) | bundled | <https://shapely.readthedocs.io/>, <https://github.com/fonttools/pyclipper> |
| OmegaConf (+ ANTLR4 runtime), PyYAML | RapidOCR settings files | BSD-3-Clause, BSD-3-Clause, MIT | bundled | <https://omegaconf.readthedocs.io/>, <https://pyyaml.org/> |
| requests, urllib3, idna, charset-normalizer, tqdm, colorlog, six | RapidOCR dependencies (never used to download anything by ConvertCAD) | Apache-2.0, MIT, BSD-3-Clause, MIT, MPL-2.0 AND MIT, MIT, MIT | bundled | <https://pypi.org/> |
| certifi | trusted certificates for the OCR model downloads (HTTPS) | MPL-2.0 | bundled | <https://github.com/certifi/python-certifi> |
| python-bidi | right-to-left order of Arabic OCR text | LGPL-3.0 | bundled | <https://github.com/MeirKriheli/python-bidi> |
| Pillow, packaging | RapidOCR dependencies | MIT-CMU (HPND); Apache-2.0 / BSD-2-Clause | bundled | <https://python-pillow.org/> |
| Inno Setup (Jordan Russell, Martijn Laan) | engine of the Windows installer (`setup.exe`) | Inno Setup License (free, BSD-style) | in the installer only | <https://jrsoftware.org/isinfo.php> |
| AppImage runtime, appimagetool | the Linux AppImage file | MIT | runtime in the AppImage only; appimagetool is a build tool | <https://appimage.org/> |
| PyInstaller | building the executable | GPL-2.0 with bootloader exception (the exception allows any licence for the built program) | build tool only | <https://pyinstaller.org/> |
| pytest, Ruff | tests, lint | MIT | development only | <https://pytest.org/>, <https://docs.astral.sh/ruff/> |

## About the PyMuPDF licence

PyMuPDF is dual-licensed: GNU AGPL-3.0, or a commercial licence sold by Artifex Software.
ConvertCAD uses it under the AGPL-3.0, which is why ConvertCAD itself is AGPL-3.0: anyone
receiving the program can obtain its complete source code. Distributing ConvertCAD in a
closed-source form requires a commercial PyMuPDF licence from Artifex.

## About GNU LibreDWG (GPL-3.0-or-later)

ConvertCAD writes DWG files by running the LibreDWG programs `dxf2dwg` and `dwg2dxf`,
shipped in the `libredwg` folder of every download. They are built from the unmodified
LibreDWG 0.13.4 source plus three small bug fixes made by ConvertCAD (duplicate linetype
entries, slow reading of large DXF files, scale of mirrored blocks). The complete
corresponding source — upstream tarball, patches and build script — is in the ConvertCAD
source repository (`vendor/libredwg/`, `scripts/build_libredwg.sh`); `SOURCE.txt` next to
the programs says where to find it. The GPL-3.0 is compatible with ConvertCAD's AGPL-3.0.

The free ODA File Converter is **not** used: its licence forbids redistributing it with
other software.

## About the Qt licence (LGPL-3.0)

The LGPL requires that users can replace the Qt libraries with their own version. In the
folder builds (`dist/ConvertCAD/`, the installers, the AppImage and the .deb), the Qt
libraries are separate files in `_internal` and can be replaced; the complete source code of
ConvertCAD is available, so the program can be rebuilt with any Qt version. The same applies
to the other LGPL components (python-bidi, GEOS).

## Icons and artwork

The application icon and the interface icons were drawn for ConvertCAD (`assets/`,
`convertcad/ui/icons.py`) and are covered by the ConvertCAD licence.
