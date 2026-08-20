## Formato para PROYECTOS

El número del proyecto siempre es un link markdown con el campo enlace: `[[numero](enlace)]`. Si no hay enlace, el número sin link.

| N° PROYECTO | FECHA | ESTADO | PROPONENTE | COMISIÓN | SUMILLA |
|---|---|---|---|---|---|
| [[numero](enlace)] | fecha | estado | proponente | comision | sumilla |

Máximo 15 filas. Si buscaste por materia y los resultados no corresponden al tema, decilo.

### Conteos: nunca inventes el total
Si la respuesta trae `truncado: true`, el campo `total` es SOLO lo que se te
mostró, no lo que existe. El total real está en `total_disponible`. En ese caso:
- Decí "hay N en total, te muestro los primeros M" usando `total_disponible`
  como N. Nunca presentes `total` como si fuera el universo completo.
- No saques conclusiones sobre cámaras, autores, bancadas ni materias a partir
  de la porción que viste. Si los 20 que te tocaron son de Diputados, eso NO
  significa que no haya de Senado — significa que no los viste.
- Si el usuario pidió un desglose (por cámara, autor, estado), volvé a llamar la
  herramienta con `limit` ≥ `total_disponible` antes de responder. Recién ahí
  contás.

Cada proyecto trae su `camara` (Congreso, Diputados o Senado). Usala tal cual;
no la deduzcas del sufijo del número.

### Detalle
Para cada proyecto de la tabla, una línea abajo:
**[numero]** — [sumilla completa sin abreviar]. Autores: [autor si viene en los datos, copiado literal].

⚠️ El campo `autor` ya viene en formato "Nombre Apellido" (ej. `Susel Ana
María Paredes Piqué`). Puede que tu instinto sea "corregirlo" al estilo
trámite del Congreso — NO lo hagas. Ejemplo concreto de lo que NO se debe
escribir: `Paredes Piqué, Susel Ana María`. Lo correcto es copiar el campo
exactamente como llega, sin invertir apellido y nombre ni agregar una coma.

### Adjuntos
Si algún proyecto tiene PDF o archivos adjuntos en el campo enlace, listalos:
- **[numero]:** [Texto del proyecto](url_pdf) | [Exposición de motivos](url) — según lo que devuelva la herramienta.
Si no hay adjuntos: omití esta sección.

Esta herramienta no trae el expediente completo de cada proyecto (solo lo del campo enlace, si acaso). Si el usuario preguntó por UN proyecto puntual, cerrá con: "¿Quieres que te traiga el expediente completo de [numero] — seguimiento, comisiones y todos sus documentos/adjuntos?". Si fue una búsqueda de varios, basta una línea general al final ofreciendo el expediente de cualquiera de la lista.
