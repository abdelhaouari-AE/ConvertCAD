# Guía de usuario de ConvertCAD

ConvertCAD convierte dibujos PDF 2D en **archivos DXF o DWG editables, creados con verdaderas entidades CAD**: líneas, polilíneas, arcos, círculos, splines, sombreados, textos y párrafos, cotas verdaderas, directrices, capas y bloques — no una maraña de líneas sueltas. Todo se ejecuta en su ordenador.

## Los cuatro pasos

1. **Abrir un dibujo** — *Abrir PDF…* (Ctrl+O), arrastre un PDF a la ventana o pruebe el plano de ejemplo. Cada hoja aparece a la izquierda con una etiqueta: **Vectorial** (ideal), **Escaneo** (se vectorizará y se leerá con OCR) o **Vacía**. Desmarque las hojas que no quiera convertir; el menú de selección de la cabecera *Hojas* selecciona todas, ninguna, solo las vectoriales o solo las escaneadas.
2. **Comprobar la escala** — elija la escala del dibujo en *Ajustes > Escala, unidades y área* (ConvertCAD la lee en el cajetín cuando puede). Para un resultado exacto, use **Calibrar** (C): haga clic en dos puntos cuya distancia real conozca — por ejemplo dos ejes — y escriba la distancia. Use **Medir** (M) para comprobar cualquier distancia antes de convertir. Para convertir solo una parte de la hoja, use **Seleccionar área** (A) y arrastre un rectángulo; *Hoja completa* la quita.
3. **Convertir** (Ctrl+Intro) — se ejecuta en segundo plano; puede seguir ampliando la vista o cancelar en cualquier momento.
4. **Revisar y guardar** — la pestaña *Resultado DXF* muestra el dibujo convertido tal como lo leerá el programa CAD. **Superponer el PDF** (O) coloca el PDF debajo, con un control de opacidad: cualquier diferencia se ve al instante. Haga clic en una entidad del resultado para seleccionarla: se resalta, la barra de estado muestra su tipo, capa y tamaño, y su capa se selecciona en *Capas*. En *Capas*, desmarque las capas que no quiera, cámbieles el nombre (doble clic) o el color (clic en la muestra); el botón ↺ deshace todos los cambios de capas. El *Informe* enumera todo lo creado, con las advertencias. Luego **Guardar DXF…** (Ctrl+S) — o **Guardar DWG…**: elija el tipo DWG en la ventana de guardado, o ponga *Ajustes > Salida > Formato de archivo* en DWG antes de convertir.

## Moverse por el dibujo

| Acción | Cómo |
|---|---|
| Zoom en el cursor | Rueda del ratón |
| Desplazar la vista | Arrastrar con el botón central, Espacio + arrastrar, o arrastrar con la herramienta Desplazar |
| Ajustar la hoja | F |
| Hoja siguiente / anterior | Av Pág / Re Pág |
| Cancelar una herramienta | Escape (el clic derecho cancela el primer punto) |

La hoja se ve nítida con cualquier zoom: la zona visible se vuelve a dibujar con la resolución de la pantalla.

## Referencia a objetos

Al medir o calibrar, los clics saltan al punto exacto del dibujo, como la referencia a objetos de AutoCAD. La barra de estado activa cada modo:

- **FIN** — puntos finales y esquinas (marcador cuadrado)
- **MED** — puntos medios de los segmentos (triángulo)
- **INT** — intersecciones (cruz)
- **CEN** — centros de círculos y arcos (círculo)

F3 activa o desactiva la referencia.

## Qué produce la conversión

| En el PDF | En el DXF |
|---|---|
| Curvas circulares | Verdaderas entidades **ARC** y **CIRCLE** |
| Curvas en varios trozos | Una **SPLINE** exacta |
| Segmentos que se tocan | Una **LWPOLYLINE** (cerrada si forma un bucle) |
| Patrones de trazos, o trazos dibujados como piezas sueltas | Una línea con un tipo de línea **CENTER**, **DASHED**, **DASHDOT**, **PHANTOM**… medido en el PDF |
| Áreas rellenas | **HATCH** sólido en la capa HATCH |
| Sombreado dibujado como muchas líneas paralelas | Un **HATCH** con patrón (ángulo y separación del PDF) |
| Arena, hormigón, grava, tierra, ladrillo, aislante o puntos dibujados como muchos trazos y puntos | Un **HATCH** con el patrón estándar (AR-SAND, AR-CONC, GRAVEL, EARTH, BRICK, INSUL, DOTS…) a la escala y con el ángulo medidos en el PDF |
| Texto | **TEXT**; las líneas apiladas forman un párrafo **MTEXT** |
| Texto SHX de AutoCAD dibujado como trazos | **TEXT** real en la capa TEXT_SHX (los trazos se conservan en la capa oculta TEXT_SHX_STROKES) |
| Flecha + línea + flecha + valor | **DIMENSION** verdadera (capa DIM) — el valor conserva el texto del PDF |
| Trazos oblicuos + línea + valor | **DIMENSION** verdadera con trazos arquitectónicos |
| Flecha sobre un círculo o un arco + valor «R…» / «Ø…» | Cota verdadera de **RADIO** / **DIÁMETRO** |
| Dos flechas sobre un arco + un ángulo («45°») o una longitud de arco | Cota verdadera **ANGULAR** / de **LONGITUD DE ARCO** — solo cuando el valor coincide con el arco dibujado |
| Flecha + línea + nota | **LEADER** / directriz múltiple (capa ANNOT_LEADER) |
| Símbolos idénticos repetidos, incluso girados en cualquier ángulo o en simetría | Un **BLOQUE** + una INSERT por aparición |
| Hojas escaneadas | **LINE**, **CIRCLE** y **ARC** en la capa TRACE_LINES, texto leído con OCR |
| Imágenes incrustadas, escaneos | Imagen en la capa bloqueada IMG_RASTER |

Los textos de medida que no corresponden a ninguna cota se colocan en la capa **DIM_RAW** (roja) para que pueda revisarlos. No se inventa nada: un patrón o una cota solo se reconstruye cuando reproduce el PDF; si no, sus piezas se conservan tal cual. La cota de longitud de arco se escribe como ARC_DIMENSION verdadera a partir del DXF 2007; en las versiones anteriores y en DWG se conserva como su dibujo en la capa DIM.

## Los ajustes

**Escala, unidades y área** — escala del dibujo (1:N) y unidad del DXF (mm, cm, m); *Seleccionar área… / Hoja completa* (solo se convierte el área, en las coordenadas propias de la hoja; el área se aplica a cada hoja convertida). *Leer la escala escrita en cada hoja* sirve para juegos de planos con escalas distintas (planta a 1:100, detalles a 1:20): cada hoja usa la escala de su cajetín, y la escala de arriba se usa cuando una hoja no indica ninguna o indica varias; el informe dice qué escala recibió cada hoja. La calibración sustituye a ambas; el panel muestra la escala equivalente («aprox. 1:100,2») como comprobación.

**Geometría** — reconstruir arcos y círculos; unir segmentos en polilíneas; unir curvas en splines únicas; *precisión de las curvas* (Fina / Normal / Holgada) fija con qué rigor una curva debe coincidir con un círculo; rellenos sólidos como sombreados; *reconstruir los patrones de sombreado* (líneas paralelas → HATCH con patrón; arena, hormigón, grava, tierra, ladrillo, aislante, puntos → el patrón estándar; la arena y el hormigón tienen aspecto aleatorio, por eso su escala y su posición son estimadas y el informe lo indica); *reconstruir las líneas discontinuas* (trazos sueltos → una línea con su tipo de línea); ignorar máscaras blancas, líneas blancas y fondos de página (ocultarían el dibujo en CAD).

**Texto** — exportar el texto; agrupar las líneas apiladas en párrafos MTEXT; *relación de altura del texto* (altura de mayúsculas ÷ tamaño de fuente del PDF, 0,70 conviene a la mayoría de las fuentes); *recuperar el texto dibujado como trazos o contornos*: el texto SHX de AutoCAD vuelve a ser texto real (capa TEXT_SHX) gracias a los comentarios ocultos que AutoCAD añade a sus PDF, y el texto TrueType dibujado como contornos rellenos se sustituye por su texto real.

**Cotas y directrices** — reconstruir las cotas con flechas (lineales, radio, diámetro, ángulo, longitud de arco) y/o con trazos oblicuos; reconstruir las directrices.

**Capas y bloques** — conservar las capas propias del PDF cuando las tiene; *nombres de capa* cuando no las tiene: color + grosor + tipo de línea (p. ej. GEO_BLACK_050_CENTER), solo color o una sola capa; reconocer los tipos de línea; *colores*: índice de color de AutoCAD (funciona con los estilos de trazado CTB) o color verdadero (RGB exacto); detectar símbolos repetidos como bloques, con un número mínimo de repeticiones, y *detectar también copias giradas y en simetría* (cualquier ángulo).

**Páginas escaneadas** — vectorizar líneas, círculos y arcos; leer el texto con OCR (modelos PP-OCR, en este ordenador); *idiomas del OCR*: inglés, francés… (alfabeto latino, integrado), otro alfabeto (árabe, cirílico, griego…) o ambos para los dibujos mixtos — solo se muestran los instalados; *precisión del OCR*: Estándar (modelo integrado) o Máxima (modelos más grandes, más lentos); **Idiomas y modelos del OCR…** descarga los demás idiomas y los modelos de precisión máxima, o los instala desde archivos en un ordenador sin internet (véase *Ayuda > Guía del OCR*); resolución de escaneo (200–600 ppp); usar la capa de texto del PDF cuando el escaneo ya permite buscar texto; conservar las imágenes ráster en una capa bloqueada.

**Salida** — *formato de archivo*: DXF, o DWG (formato AutoCAD 2000: se abre en todos los AutoCAD desde 2000 y en todos los programas CAD actuales; lo escribe el conversor GNU LibreDWG incluido y se comprueba tras escribirlo); versión DXF (R2018 para los programas actuales, R12 para máquinas CNC antiguas); con varias hojas, un DXF con las hojas una al lado de otra o un DXF por hoja; escribir un registro de conversión junto al DXF; abrir la carpeta después de guardar.

**Perfiles** — ajustes listos para usar: Recomendado, Planos de arquitectura, Planos de estructura / encofrado, Planos escaneados de archivo, Solo geometría, CNC / láser. *Guardar como perfil…* conserva sus propias combinaciones.

## Idioma de la interfaz

*Ver > Idioma*: English, Français, Español, Deutsch o العربية (árabe, escrito de derecha a izquierda: toda la ventana se invierte, los dibujos no). El cambio se aplica en el siguiente inicio. Los idiomas del OCR se eligen aparte (*Ajustes > Páginas escaneadas*).

## Actualizaciones

ConvertCAD nunca se conecta a internet por sí solo. *Ayuda > Buscar actualizaciones…* pregunta una vez a GitHub si existe una versión más reciente; *Ayuda > Buscar actualizaciones al iniciar* lo hace en cada inicio (desactivado por defecto). No se envía nada y no se instala nada: cuando existe una versión más reciente, ConvertCAD muestra su número y puede abrir su página de publicación.

## Convertir una carpeta entera

*Convertir una carpeta…* (Ctrl+B) convierte todos los PDF de una carpeta (opcionalmente con subcarpetas) con los ajustes actuales. Cada archivo obtiene su DXF (o DWG) y su registro en la carpeta de salida. La calibración no se aplica en este modo: por defecto cada hoja usa la escala escrita en su cajetín y, si no, la escala del dibujo de los ajustes — compruébela en cada registro.

Las mismas conversiones pueden automatizarse con el programa de consola *ConvertCAD-cli.exe* (junto a ConvertCAD.exe) — escriba `ConvertCAD-cli --help` en un símbolo del sistema.

## Comprobaciones tras cada conversión

1. Mida una distancia conocida en CAD para confirmar la escala.
2. Muestre solo la capa DIM y compare algunos valores con el PDF.
3. Revise la capa DIM_RAW.
4. Lea las advertencias del informe.

## Solución de problemas

- **El texto llega como pequeños trazos** — el PDF se generó con fuentes SHX sin los comentarios ocultos (no es un PDF de AutoCAD, o se exportó sin ellos): los trazos quedan como geometría. Para los PDF de AutoCAD, deje activado *Recuperar el texto dibujado como trazos o contornos*.
- **Una zona blanca oculta el dibujo en CAD** — deje activado *Ignorar máscaras blancas, líneas blancas y fondos de página*.
- **El OCR es deficiente** — compruebe los *idiomas del OCR* (un dibujo en cirílico o árabe necesita su alfabeto: *Idiomas y modelos del OCR…*); para escaneos de mala calidad o textos pequeños elija *Precisión del OCR: Máxima* o una resolución de escaneo mayor; véase *Ayuda > Guía del OCR*.
- **Falla una descarga del OCR** — compruebe la conexión a internet o el proxy de la empresa; en un ordenador sin internet use *Instalar desde archivo…* (véase *Ayuda > Guía del OCR*).
- **No se pudo escribir el DWG** — el informe dice por qué, y el dibujo se guarda en DXF en su lugar; envíe el PDF con el registro si vuelve a ocurrir.
- **Demasiadas capas pequeñas** — elija *Solo color* o *Una sola capa de geometría*, o desmarque capas antes de guardar.
- **Un símbolo repetido no se convirtió en bloque** — sus copias difieren (tamaño, una pieza que falta) o aparece menos veces que *Repeticiones mínimas*.
- **Un sombreado quedó como muchas líneas pequeñas** — no coincidía lo bastante con ningún patrón estándar (patrón personalizado, varios patrones que se tocan): sus piezas se conservan, no se inventa nada.
- **Una conversión es lenta** — escaneos muy grandes: baje la resolución de escaneo.

ConvertCAD {APP_VERSION} — © {APP_YEAR} {APP_AUTHOR}
