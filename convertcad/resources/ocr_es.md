# OCR de los PDF escaneados

ConvertCAD vectoriza las líneas, círculos y arcos de los dibujos escaneados y **lee su texto** con los modelos **PP-OCR** de PaddleOCR, ejecutados en este ordenador por RapidOCR y ONNX Runtime. Encuentran líneas de texto completas en cualquier lugar de la hoja — pequeñas, giradas, verticales o cruzadas por líneas. Ningún dibujo sale del ordenador.

## Idiomas

Elíjalos en *Ajustes > Páginas escaneadas > Idiomas del OCR*:

| Opción | Lee | Modelo |
|---|---|---|
| **Inglés, francés… (alfabeto latino)** — por defecto | inglés, francés, español, alemán, italiano, portugués, neerlandés, polaco, turco, vietnamita y otros 37 idiomas de alfabeto latino; también chino y japonés | **integrado** (unos 30 MB) |
| **Árabe**, **Cirílico**, **Griego**, **Coreano**, **Devanagari**, **Tailandés**, **Tamil**, **Telugu** | ese alfabeto (el árabe también lee persa y urdu; el cirílico lee ruso, ucraniano, búlgaro, serbio…) | descarga |
| **Inglés, francés… + Árabe** (u otro alfabeto) | dibujos que mezclan ambos, p. ej. un plano en francés con un cajetín en árabe: cada línea conserva la lectura de su propio alfabeto | integrado + descarga |

Solo se muestran los idiomas instalados. Una opción cuyo modelo falta (ajustes copiados de otro ordenador, modelo eliminado) sigue visible, marcada *(no descargado)*: se usa en su lugar el modelo integrado, y el informe lo indica.

## Precisión

- **Estándar** (por defecto) — el modelo integrado: rápido, y la opción adecuada para casi todos los dibujos.
- **Máxima** — modelos más grandes (descarga, 132 MB): algo mejores con escaneos de mala calidad, pero unas 20 veces más lentos (medido: 83 % de los textos de una hoja de prueba leídos en lugar de 81 %). Se aplica a los idiomas de alfabeto latino; los demás alfabetos tienen un solo modelo cada uno.

## Descargar idiomas y modelos

*Ajustes > Páginas escaneadas > Idiomas y modelos del OCR…* (también en el menú *Herramientas*):

1. Elija un modelo en la lista (se indica su tamaño) y luego **Descargar**. Una barra de progreso sigue la descarga; **Cancelar** la detiene.
2. Cada archivo se comprueba (SHA-256) antes de conservarlo: una descarga interrumpida o dañada nunca deja un modelo defectuoso.
3. Después el modelo funciona **sin conexión, para siempre**. **Eliminar** lo borra.

Dónde se guardan los modelos:

| ConvertCAD | Carpeta |
|---|---|
| Windows (instalador o zip portátil) | `%LOCALAPPDATA%\ConvertCAD\ocr_models` |
| Linux (AppImage, .deb, tar.gz) | `~/.local/share/convertcad/ocr_models` |
| Modo portátil (un archivo vacío `ConvertCAD.portable` junto al programa) | la carpeta `ocr_models` junto al programa: los modelos viajan con él |

La variable de entorno `CONVERTCAD_OCR_MODELS` permite elegir otra carpeta. Desinstalar ConvertCAD en Windows elimina los modelos descargados; actualizarlo los conserva.

**De dónde vienen:** la publicación de GitHub `ocr-models-v1` de ConvertCAD o, si no, el repositorio de modelos de RapidOCR (ModelScope). Solo se descarga el archivo solicitado; no se envía nada, ni dibujos ni información sobre usted. Se usa automáticamente el proxy de la empresa cuando está configurado en el sistema (o en la variable `HTTPS_PROXY`).

**Ordenador sin internet:** en otro ordenador, abra la página de descarga (botón *Página de descarga*), descargue los archivos `.onnx` del modelo, cópielos (memoria USB…) y luego haga clic en **Instalar desde archivo…** — los archivos se reconocen por su suma de control, sea cual sea su nombre.

**Línea de comandos:** `ConvertCAD-cli --list-ocr` enumera los modelos, `ConvertCAD-cli --get-ocr-model arabic latin_max` los descarga y luego `--ocr-lang latin+arabic --ocr-quality maximum` los usa.

## Consejos

- 300 ppp es un buen valor por defecto. Use 400–600 ppp para textos pequeños en hojas grandes (más lento).
- El texto vertical se lee sin ningún ajuste adicional.
- Cuando un PDF escaneado ya permite buscar texto (contiene una capa de texto), ConvertCAD usa ese texto en lugar del OCR.
- Desde el código fuente: `pip install -r requirements.txt` instala RapidOCR, ONNX Runtime y el modelo integrado.
