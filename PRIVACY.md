# ConvertCAD privacy policy

*Applies to ConvertCAD 1.2.2 and later. Last update: 2 November 2026.*

ConvertCAD converts drawings **on your computer**. Your PDF files, the converted
DXF / DWG files and your settings are never sent anywhere. There is no account,
no advertising, no analytics and no tracking.

ConvertCAD connects to the internet only in these three cases, each started by you:

| When | What is contacted | What is sent |
|---|---|---|
| You download an OCR language (Tools > OCR languages and models) | GitHub (`github.com`) and, if GitHub fails, the ModelScope mirror (`modelscope.cn`) | A normal download request (your IP address, as for any download) |
| You check for updates (Help > Check for updates, or the Updates button). The check at startup is **off** by default and can be switched off again in the Help menu | The GitHub API (`api.github.com`) | A normal web request; nothing about you or your drawings |
| You click *Feedback* | Your web browser opens the ConvertCAD form on Tally (`tally.so`) | Only what you type in the form, plus the ConvertCAD version, the operating system and the interface language written in the form address. Tally's own privacy policy applies to the form |

The usage data that ONNX Runtime (the OCR engine) can send to Microsoft is
switched off by ConvertCAD.

Data stored on your computer: settings and the log file in the folder
`.convertcad` of your user profile, and the OCR models you downloaded. Uninstalling
ConvertCAD removes the program and the downloaded OCR models; the settings
folder can be deleted by hand.

Questions: open the Feedback form or an issue on
<https://github.com/abdelhaouari-AE/ConvertCAD/issues>.
