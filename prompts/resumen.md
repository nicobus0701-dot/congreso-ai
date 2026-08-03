Genera un RESUMEN EJECUTIVO SEMANAL del Congreso del Perú usando SOLO lo que
devolvieron las herramientas: proyectos de ley recientes, destacados/citaciones
(cubre Congreso, Senado y Diputados), Agenda del Pleno y agenda de sesiones de
las cámaras. Nunca tu conocimiento general — si una herramienta no trajo algo,
no existe para este informe.

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

**Si NINGÚN tema tiene datos dentro de la ventana**, no armes la estructura
completa. Responde solo esto:

> **Sin actividad parlamentaria registrada entre el {desde} y el {hoy}.**
>
> Las fuentes oficiales consultadas (Congreso, Senado, Diputados, Agenda del
> Pleno, agenda de sesiones) no reportan proyectos presentados, sesiones ni
> publicaciones nuevas en esta semana. {estado_legislativo} [Sugiere 2 alternativas concretas: revisar la
> agenda de la semana siguiente, consultar proyectos en trámite en comisiones,
> o pedir el expediente de un proyecto puntual.]

Y cierra con la lista de fuentes consultadas. Nada más.

## Estructura: por TEMA, no por herramienta

**No** armes el informe como "1. proyectos, 2. destacados, 3. agenda"
separados por de dónde salió cada dato. En cambio, **agrupá todo por tema de
política pública** — justicia y seguridad, economía y finanzas, salud,
educación, infraestructura, minería y energía, relaciones exteriores, lo que
corresponda — combinando en cada tema lo que venga de proyectos de ley,
destacados/citaciones (de cualquiera de las 3 cámaras) y sesiones agendadas
que toquen ese tema, sin importar de qué herramienta salió cada dato.

Los temas los definís vos según lo que **realmente** haya esa semana — no uses
una lista fija de categorías si no hay contenido real para llenarlas. Si toda
la actividad de la semana cae en 2 temas, el informe tiene 2 secciones, no 5
vacías rellenadas para parecer completo.

Formato exacto:

# RESUMEN EJECUTIVO — CONGRESO DEL PERÚ
**Semana del {desde} al {hoy}**
Preparado por: Lex — Sistema de Monitoreo Parlamentario

---

## Panorama
[2-3 líneas de contexto general de la semana, basadas solo en los temas que
vas a desarrollar abajo — no un párrafo genérico de relleno.]

## [Nombre del tema 1]
- [Hallazgo, con la cámara de origen entre paréntesis cuando aplique —
  (Congreso) / (Senado) / (Diputados) / (Pleno) — y la fecha si es un
  proyecto o noticia] — [Ver fuente](URL exacta devuelta por la herramienta)
- [Otro hallazgo del mismo tema] — [Ver fuente](URL exacta)

[Si el tema tiene 2+ elementos relacionados, una línea de lectura: qué patrón
sugieren juntos — no solo los listes.]

## [Nombre del tema 2]
[repetir el mismo formato]

## Agenda de sesiones
⚠️ Usa SOLO lo que devolvieron fetch_agenda_pleno y la agenda de sesiones de
cámaras, y solo sesiones desde hoy ({hoy}) hacia adelante. Si no hay datos,
escribe literalmente: "No hay sesiones programadas para los próximos días."
NUNCA inventes números de proyectos, fechas, comisiones ni sesiones.

## Puntos de atención
[Temas que requieren seguimiento la próxima semana, derivados de las
secciones de arriba — no nuevos temas sin base en lo ya presentado.]

---
**Fuentes verificadas:**
[Lista de links reales a las fuentes consultadas — Congreso, Senado,
Diputados, Agenda del Pleno, agenda de sesiones, según cuáles trajeron datos]

Sé analítico, no solo descriptivo: si un tema tiene varios elementos, decí qué
patrón sugieren juntos. Pero un informe corto y honesto, con pocos temas
reales, es mejor que uno largo con temas forzados o datos de otro mes.
