# GNU LibreDWG — the DWG converter bundled with ConvertCAD

ConvertCAD saves DWG files with **GNU LibreDWG 0.13.4**. LibreDWG is free
software, licensed under the **GNU General Public License v3.0 or later**
(see `COPYING`), and the free software licence lets ConvertCAD ship it inside
the portable folder, the installers, the AppImage and the .deb. Users don't
install anything.

| File | What it is |
|---|---|
| `libredwg-0.13.4.tar.xz` | Unmodified upstream source, from <https://github.com/LibreDWG/libredwg/releases/tag/0.13.4> (SHA-256 `7e153ea4dac4cbf3dc9c50b9ef7a5604e09cdd4c5520bcf8017877bbe1422cd5`) |
| `patches/*.patch` | ConvertCAD's three fixes (see below), applied in order |
| `win64/dxf2dwg.exe`, `win64/dwg2dxf.exe` | Windows 64-bit programs built from the two items above with MinGW-w64 GCC 13 (static, stripped) |
| `win64/libssp-0.dll` | GCC stack-protector runtime used by those programs (GPL-3.0 with the GCC Runtime Library Exception) |
| `linux-x86_64/` | Linux programs, built on demand by `scripts/build_libredwg.sh linux` (not stored in Git) |
| `COPYING` | The GNU GPL v3 |
| `SOURCE.txt` | Where to find the corresponding source (copied next to the bundled programs) |

## Why a patched build?

LibreDWG 0.13.4 has three bugs in its DXF reader (`src/in_dxf.c`) that
ConvertCAD's drawings hit. Each patch is a few lines; nothing else is changed.

| Patch | Bug |
|---|---|
| `01-ltype-control-entries.patch` | At the end of a linetype record a test is inverted, so every linetype is added a second time to the DWG linetype table. LibreCAD's DWG reader rejects such a file ("LineType control parse failed") and AutoCAD would have to repair it. |
| `02-dxf-read-string-speed.patch` | For every character of every string it reads, the reader called `strlen()` on the whole rest of the file: reading a 10 MB DXF took 4 minutes. With a bounded test it takes 9 seconds, and the DWG is byte-for-byte the same. |
| `03-point-keeps-own-values.patch` | A point given without its Y / Z values took the Y / Z of the point read before it. A mirrored block reference written with only its X scale (-1) got the Y and Z of its insertion point as scale factors: the block came out stretched hundreds of times. |

With the patches, ConvertCAD's DWG files open in LibreCAD's independent reader
(libdxfrw) with the same entities, layers, blocks and linetypes as the DXF.
ConvertCAD also completes the INSERT scale factors itself, so an unpatched
LibreDWG found on the system PATH produces correct files too.

## Rebuilding

```bash
./scripts/build_libredwg.sh windows   # cross-compile (needs gcc-mingw-w64-x86-64)
./scripts/build_libredwg.sh linux     # native (needs gcc, make, xz)
```

## What LibreDWG writes

DWG **AutoCAD 2000 format (AC1015)**. Every AutoCAD release since 2000 and
every current CAD program opens it. LibreDWG cannot yet write newer DWG
versions. Every DWG is read back after writing (`dwg2dxf`) and ConvertCAD
checks that no entity was lost and that every block reference kept its
position, scale and rotation.

## Why not the ODA File Converter?

The free ODA File Converter may not be redistributed with other software
(ODA Community User Agreement, section 3.1.1), and non-members may use it
for non-commercial purposes only. LibreDWG has no such limits.
