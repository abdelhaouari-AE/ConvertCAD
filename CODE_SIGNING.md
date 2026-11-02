# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io),
certificate by [SignPath Foundation](https://signpath.org).

## What is signed

The Windows programs built by the public GitHub Actions workflow
[`build.yml`](.github/workflows/build.yml) from the source code of this repository:

- `ConvertCAD.exe` and `ConvertCAD-cli.exe` (in the installer and in the portable zip)
- the installer `ConvertCAD-<version>-win64-setup.exe`

Third-party programs shipped with ConvertCAD (for example the GNU LibreDWG
converters `dxf2dwg.exe` / `dwg2dxf.exe`) are **not** signed with this certificate.

## Team roles

| Role | Members |
|---|---|
| Committers and reviewers | [abdelhaouari](https://github.com/abdelhaouari-AE) |
| Approvers | [abdelhaouari](https://github.com/abdelhaouari-AE) |

Changes from other contributors are only merged after review by a committer.
Every signing request is approved by hand by an approver, release by release.
All team members use multi-factor authentication on GitHub and SignPath.

## Privacy

See the [privacy policy](PRIVACY.md): ConvertCAD sends no data on its own; it goes
online only when the user downloads an OCR language, checks for updates or opens the
feedback form.
