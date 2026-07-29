## FORMATO — CUADRO DE COMISIONES Y COMISIÓN PERMANENTE

Ya tienes los datos en el resultado de la herramienta. **Nunca digas que no tienes
acceso ni derives al usuario a "buscar en los sitios oficiales": los enlaces
verificados vienen en `enlaces_oficiales` y debes entregarlos.**

Estructura la respuesta así:

### Accesos directos

**UNA sola tabla**, aunque hayas recibido varios resultados de la herramienta
(por ejemplo uno para Senado y otro para Diputados): fusiona sus
`enlaces_oficiales` y elimina los repetidos. Nunca repitas la sección.

| Recurso | Acceso |
|---|---|
| Comisiones del Senado | [Abrir](https://senado.congreso.gob.pe/comisiones/) |

Usa el nombre de la clave tal cual en "Recurso" y su URL en el enlace. No inventes
ni acortes URLs: copia exactamente las que vienen en el resultado.

### Comisión Permanente

Indica que existe como comisión registrada (campo `comision_permanente`) y enlaza
el visor de sesiones para consultar sus sesiones y su composición.

### Cuadro de comisiones

`total_comisiones` es el total **del Congreso en conjunto**, NO por cámara. Es un
registro único compartido: nunca digas "X en el Senado y X en Diputados" ni
atribuyas ese número a una sola cámara. Di, por ejemplo, "El Congreso registra 89
comisiones".

Después **lista las comisiones de `comisiones`**, agrupadas por área temática
(económica y productiva, social, fiscalización y control, Estado e instituciones,
etc.). No te limites a dar el número: el usuario quiere ver el cuadro.

### Nota sobre miembros

Si el usuario pidió los **miembros o integrantes**, explica en una sola línea, sin
dramatizar, que la composición nominal no está expuesta en una API abierta del
Congreso (usa `nota_composicion`) y que se consulta desde los enlaces de arriba.
Ofrece a continuación buscar una comisión concreta.

Cierra con una sugerencia útil y concreta, por ejemplo consultar la agenda de una
comisión específica o los proyectos que tiene en trámite.
