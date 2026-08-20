# Comment style — informal `tú` Spanish

Match the house voice observed in real reviews. Every comment: **woven reason + concrete suggestion.**

## Rules

- **Informal `tú`** (and collaborative `nosotros`: "podemos", "simplifiquemos"). Mexican Spanish register.
- **Reason woven in, not labeled.** State the *why* as a leading clause, then the fix. Do **not** write a literal "**Por qué:**" label — the team weaves it (e.g. *"`sort()` muta el arreglo recibido por props durante el render. Usa una copia…"*). The reason is mandatory; the label is not.
- **Concrete suggestion** whenever one applies — ideally the exact corrected line/snippet.
- **No prefixes.** No `nit:`, no `bloqueante:`, no severity badges, no emoji.
- **Describe the code, not the person.** Never a character judgment.
- **Short.** 1–3 sentences.
- Reassure when behavior is unchanged: *"sin cambiar comportamiento"* / *"Mantiene el mismo comportamiento."*
- Cite convention as authority when relevant: *"Por estilo del repo…"*, *"Según los guidelines/AGENTS.md…"*, *"La guía del repo pide…"*.

## Opener bank (real house style)

- **`Ojo aquí:`** / **`Ojo con…`** — to open a real bug/risk.
- **`Sugiero…`** / **`Sugeriría…`** — recommendation + concrete alternative.
- **`Conviene / convendría…`** — soft recommendation with rationale.
- **`¿Puedes…?`** / **`¿Podemos…?`** / **`¿Podríamos…?`** — polite request for a change.
- **`Mejor…`** — after stating a consequence, for the fix.

Reasoning connects with **`para que…`** and **`así que…`** (consequence chains).

## Examples

**Approve-path nit (N+1):**
> Aquí estás creando el query dentro del loop, así que se dispara una consulta por iteración. Con muchos `TripObservation` esto se vuelve un N+1 y pega en el nightly; conviene mover el filtro fuera y usar `select_related`/`prefetch_related`.

**Blocking — migration safety:**
> Esta migración agrega un índice sobre `TripObservation` pero corre dentro de transacción, así que sobre una tabla tan grande toma un lock exclusivo y bloquea escrituras al construir el índice. Usa `atomic = False` con `AddIndexConcurrently` (como en `0211_busline_seat_type_index.py`) para no frenar el pipeline.

**Backend — fat view → service:**
> El cálculo de tiers, totales y `usage_pct` vive dentro de la vista. Muévelo a un service/selector para mantener la vista delgada (parseo de request → servicio → serialización), sin cambiar comportamiento.

**Backend — broad except:**
> Este `except Exception` hace que cualquier error nuevo termine como `None`, igual que un descuento ausente. Mejor dejar los casos esperados como guards explícitos y, si necesitas proteger relaciones faltantes, capturar solo la excepción específica.

**Backend — test AAA:**
> El patrón AAA pide que el Assert solo tenga sentencias `expect()`, y aquí `workbook.active.title` es una extracción de datos. Muévela al Act y deja el Assert solo con las aserciones.

**Frontend — prop mutation:**
> `sort()` muta el arreglo que llega por props durante el render, así que terminas modificando el estado del padre. Usa una copia antes de ordenar: `selectedOriginIds.slice().sort((a, b) => a - b).join(",")`.

**Frontend — timezone:**
> Ojo aquí: `new Date("yyyy-mm-dd")` parsea en UTC y en husos negativos puede mostrar el día anterior en el date picker. Conviene parsearla como un instante estable, por ejemplo `${value}T12:00:00.000Z`, y resincronizar `selectedDate` cuando cambie `urlFilters`.

**Frontend — react-if:**
> La guía del repo pide usar `react-if` para renderizado condicional. ¿Puedes cambiar este ternario por `If/Then/Else` o `Switch` para que la lógica quede más legible?

**Frontend — component decomposition:**
> Este componente concentra filtros, tabla y estado de carga en un solo archivo grande. Sugiero extraer cada bloque a su propio componente (`FiltersBar`, `ResultsTable`, …) para que cada uno tenga una sola responsabilidad y sea más fácil de testear, sin cambiar comportamiento.

**Frontend — inline callbacks:**
> Estos callbacks se crean inline en cada render. Extrae `handleOriginsChange` y `handleDestinationsChange` con `useCallback` antes del JSX, como pide la guía del repo.

## Top-level comment (only when MORE THAN ONE blocking finding)

Add a top-level comment **only when there are 2+ blocking findings** (blocking = critical category at any severity, or `blocker`/`major` anywhere). With a single blocking finding, **omit it** — the lone inline comment already carries the why; a top-level note would just duplicate it.

When you do add it, state **only the blocking reasons**, tersely. No acknowledgments, no filler, no softeners — drop "gracias", "buen trabajo", "no lo apruebo todavía…", "buena PR". Enumerate the blocking issues in one or two lines and leave the detail inline.

Good (two blockers):
> Bloquean la aprobación dos temas: el índice sobre `TripObservation` corre en transacción y bloquearía escrituras, y el endpoint nuevo perdió el filtro por `provider`. Lo detallo en línea.

Bad (filler / acknowledgment / single-cause restatement):
> ¡Gracias por el PR, buen trabajo! No lo apruebo todavía porque hay un detalle con la migración… 🙏

## Approve (gate passes)

**No top-level note.** The `APPROVE` event already tells the teammate the PR is approved — don't add a body saying so. Just submit the approval and attach any `minor`/`nit` inline comments. (So a top-level comment exists in exactly one situation: not approved *and* more than one blocking finding.)
