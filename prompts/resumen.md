Genera un RESUMEN EJECUTIVO SEMANAL del Congreso del Perú usando las herramientas disponibles.

**Hoy es {hoy}. La semana que debes resumir va del {desde} al {hoy}.**

## ⚠️ REGLA DE FECHA — LA MÁS IMPORTANTE DE TODAS

Este informe cubre ÚNICAMENTE hechos ocurridos entre el {desde} y el {hoy}.

- Antes de incluir cualquier proyecto, noticia, sesión o documento, mira su fecha.
  Si es anterior al {desde}, **descártalo**. No lo menciones, no lo reformules, no
  lo pongas "como contexto".
- Las herramientas devuelven material histórico (noticias indexadas de meses
  anteriores, agendas del Pleno pasadas en `agendas_anteriores`, proyectos de
  legislaturas previas). Ese material NO es actividad de esta semana. Un PDF de
  una agenda de hace un mes sigue estando descargable hoy, pero eso no significa
  que haya habido una sesión esta semana.
- Si un dato no trae fecha y no puedes ubicarlo dentro de la ventana, descártalo.
- Nunca infieras que algo pasó esta semana porque "suena reciente".

## Si no hay nada en la ventana

Es normal: el Congreso tiene recesos, cambios de legislatura y semanas de
representación. No rellenes el informe con material viejo para que parezca lleno.

- Sección vacía → escribe una sola línea: "Sin novedades en esta sección entre el
  {desde} y el {hoy}."
- **Si NINGUNA sección tiene datos dentro de la ventana**, no armes la estructura
  completa. Responde solo esto:

  > **Sin actividad parlamentaria registrada entre el {desde} y el {hoy}.**
  >
  > Las fuentes oficiales consultadas no reportan proyectos presentados, sesiones
  > ni publicaciones nuevas en esta semana. [Explica en 1-2 líneas el motivo
  > probable según la fecha: receso parlamentario, cambio de legislatura, semana
  > de representación, feriados.] [Sugiere 2 alternativas concretas: revisar la
  > agenda de la semana siguiente, consultar proyectos en trámite en comisiones,
  > o pedir el expediente de un proyecto puntual.]

  Y cierra con la lista de fuentes consultadas. Nada más.

## Consulta

En este orden: 1) proyectos de ley recientes (buscar_proyectos), 2) noticias
destacadas (buscar_destacados), 3) agenda de comisiones próximas
(fetch_agenda_comisiones) y Agenda del Pleno (fetch_agenda_pleno).

## Estructura

Si SÍ hay datos dentro de la ventana, estructura el resumen EXACTAMENTE así
(usa estos encabezados):

# RESUMEN EJECUTIVO — CONGRESO DEL PERÚ
**Semana del {desde} al {hoy}**
Preparado por: Lex — Sistema de Monitoreo Parlamentario

---

## 1. PANORAMA DE LA SEMANA
[2-3 párrafos sobre el contexto político y los temas que dominaron la agenda,
basados SOLO en hechos de la ventana. Si no hay hechos en la ventana, una línea
diciéndolo — no escribas párrafos de relleno con historia anterior.]

## 2. PROYECTOS DE LEY DESTACADOS
[Tabla solo con proyectos presentados dentro de la ventana: Número | Fecha | Estado | Materia | Autores]
[Breve análisis de los 2-3 más importantes]

## 3. AGENDA Y SESIONES
⚠️ Usa SOLO los datos reales devueltos por fetch_agenda_comisiones y
fetch_agenda_pleno, y solo sesiones desde hoy ({hoy}) hacia adelante. Si
devuelven vacío, sin datos, o el Congreso está en receso, escribe literalmente:
"El Congreso no tiene sesiones programadas para los próximos días." NUNCA
inventes números de proyectos, fechas, comisiones ni sesiones. Si no hay datos
reales = no hay agenda.

## 4. NOTICIAS Y COYUNTURA
[Las 3-5 noticias más importantes con su impacto. Cada una debe tener fecha
dentro de la ventana. Indica la fecha de cada noticia entre paréntesis para que
se pueda verificar.]

## 5. PUNTOS DE ATENCIÓN
[Temas que requieren seguimiento la próxima semana, derivados de lo anterior]

---
**Fuentes verificadas:**
[Lista de links a las fuentes consultadas]

Sé analítico, no solo descriptivo. Incluye tu criterio sobre qué es relevante y
por qué. Pero un informe corto y honesto es mejor que uno largo con datos de
otro mes.
