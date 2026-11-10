# ConvertCAD privacy policy

*Applies to ConvertCAD 1.4.0 and later. Last update: 10 November 2026.*

ConvertCAD converts drawings **on your computer**. Your PDF files, the converted
DXF / DWG files and your settings are never sent anywhere. There is no account,
no advertising, no analytics and no tracking.

ConvertCAD connects to the internet only in these cases:

| When | What is contacted | What is sent |
|---|---|---|
| You download an OCR language (Tools > OCR languages and models) | GitHub (`github.com`) and, if GitHub fails, the ModelScope mirror (`modelscope.cn`) | A normal download request (your IP address, as for any download) |
| Update check: at most **once a day**, during a quiet moment (never while ConvertCAD starts; **on** by default; switch it off with Help > *Check for updates automatically*), and when you click *Updates* or Help > *Check for updates* | The GitHub API (`api.github.com`) | A normal web request; nothing about you or your drawings |
| You click *Update and restart*: ConvertCAD downloads only the files that changed in the new version | GitHub (`github.com` and its file storage) | Normal download requests; nothing about you or your drawings |
| You click *Feedback* | Your web browser opens the ConvertCAD form on Tally (`tally.so`) | Only what you type in the form, plus the ConvertCAD version, the operating system and the interface language written in the form address. Tally's own privacy policy applies to the form |

The usage data that ONNX Runtime (the OCR engine) can send to Microsoft is
switched off by ConvertCAD.

Data stored on your computer: settings and the log file in the folder
`.convertcad` of your user profile, and the OCR models you downloaded. Uninstalling
ConvertCAD removes the program and the downloaded OCR models; the settings
folder can be deleted by hand.

## The website

The ConvertCAD website (`abdelhaouari-AE.github.io/ConvertCAD`) counts its
visits with [GoatCounter](https://www.goatcounter.com/privacy): no cookies,
no IP address stored, no tracking across sites. Only totals are kept: pages
viewed, clicks on the download buttons, referring site, country, browser,
operating system, language and screen width. The program itself sends none
of this.

Questions: open the Feedback form or an issue on
<https://github.com/abdelhaouari-AE/ConvertCAD/issues>.
