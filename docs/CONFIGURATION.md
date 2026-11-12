# Configuración · esquema 1

Toda la configuración operativa está en la entrada de integración y sus opciones;
no hay que editar constantes Python ni rellenar entidades de una casa concreta.
Los perfiles JSON de `examples/` documentan el esquema interno; **no existe
importador JSON en la interfaz de la alfa**.

## Desde Dispositivos y servicios

Tras instalar el código con HACS/Marketplace, abrir **Ajustes → Dispositivos y
servicios → Añadir integración → Home Climate Orchestrator**. El asistente pide
nombre/zona horaria/tarifa, unidad exterior y los splits con sus sondas. No se
configura a través de un dashboard ni requiere YAML. La candidata añade un alta
rápida de siete campos, sin registros internos ni parámetros avanzados obligatorios.

Desde la ficha de integración, **Configurar** abre:

| Grupo | Ajustes |
|---|---|
| Equipos y sondas | Vincular split o deshumidificador; editar equipo, sondas/área, objetivos o prioridad/permisos/compensación. |
| Unidades exteriores | Añadir y editar instalaciones, sentido compartido y tiempos mínimos. |
| Confort y horarios | Selector Precio/Equilibrado/Confort/Anterior, aplicación opt-in; tablas por precio, día/sueño y regulación por ámbito. |
| Consumo y medidores | W/kW y energía al ámbito real; selección sin solapes para subtotal y contadores por periodo con cobertura. |
| Fuentes y funcionamiento | Exterior, presencia y permisos globales, calidad/origen por fuente, fuente/tipo de tarifa, observación/control y protección. |

El nombre y área vacíos se pueden completar desde el registro del equipo
seleccionado; no se deduce un área por el nombre de una entidad. Se comprueban
los tipos/unidades conocidos y se rechaza un split duplicado en la misma casa.
Las asignaciones opcionales pueden borrarse de verdad: lo mostrado es una
sugerencia de interfaz, no un valor que se restaura al enviarlo vacío.

El menú de cada habitación añade **Preferencias** y **Presencia y actividad**:
márgenes y esperas explícitos, cero o varias fuentes de estados configurables,
sin exigir sensores de presencia. El selector es una preferencia, no una orden
al equipo. En observación se comparan perfiles en salidas separadas y se
conservan las metas actuales. Ver [contrato y ejemplos](STRATEGIES_ACTIVITY.md).

Los dispositivos de regulación son servicios lógicos con acceso a la configuración
nativa. El equipo físico permanece en su integración original: no se reempareja,
no se apropian sus identificadores ni se sustituye el driver del fabricante.

### Regulación por ámbito (candidata 0.2.0a9)

**Confort y horarios → Regulación por ámbito** reparte los 49 ajustes existentes,
sin cambiar su significado, en seis formularios:

| Formulario | Qué ajusta |
|---|---|
| Calor y frío | Histéresis, ganancia, compensación, mantenimiento continuo y estabilidad térmica. |
| Sesiones de secado | Suelos, margen/offset opcional, exterior, tiempos, intentos, concurrencia y presupuesto de servicio. |
| Demanda de humedad | Persistencia, recuperación, deuda, umbrales fuertes y sus plazos. |
| Potencia y carga compartida | Presupuesto W, referencias de carga, relajación y esperas entre retiradas. |
| Frescura y cadencia de órdenes | Edad admisible de las fuentes y separación entre órdenes ordinarias; no es el reloj del planificador. |
| Precios y anticipación | Horizonte, mejora útil y entrada/salida de precio extremo. |

**Todos los ajustes (avanzado)** conserva el formulario completo. Guardar un
grupo no toca los demás; por ejemplo, un cambio de potencia no elimina el
offset opcional de secado. Borrar el offset en su formulario sí vuelve al suelo
predeterminado. Las relaciones inválidas señalan los campos implicados y no
guardan nada. Cambiar ajustes no renueva sesiones/deuda ni concede autoridad;
los cambios estructurales siguen usando la recarga habitual de la integración.

### Calidad y origen de las fuentes

**Fuentes y funcionamiento → Calidad y origen de las fuentes → Configurar una
fuente** permite seleccionar una fuente vinculada por nombre e identificador:

- **Recepción:** usa la fecha de recepción de HA; no prueba una medida física
  nueva ni modifica el límite de frescura general de esa magnitud.
- **Origen:** exige exactamente un atributo o una entidad con la fecha de la
  medida. Admite segundos Unix o una fecha con zona horaria. La falta de esa
  fecha en ejecución sigue siendo dato de origen inválido, sin respaldo
  silencioso a recepción.
- **Proveedor:** declara el contrato del proveedor de la entidad; no fabrica
  una fecha de origen ni equivale a verificar una medida nueva.

Las dos rutas de fecha son opcionales y realmente borrables. No se acepta
origen sin fecha, dos rutas a la vez, ni una fecha explícita con otra semántica.
**Volver al contrato predeterminado** elimina solo el contrato seleccionado,
preserva los demás y vuelve a recepción. El editor **Objeto completo
(avanzado)** se conserva y usa el mismo esquema y consumidor runtime.

Estas opciones son persistentes en la entrada de HA; no requieren editar YAML
ni código Python. No habilitan control ni eliminan Manual al guardarse o recargar.

## Objetivos editables como entidades

Cada split expone cuatro tablas como entidades nativas `number`, con categoría
**Configuración**, área y etiquetas de la zona: calor/frío × día/sueño, una
celda por tramo (24 ajustes con los seis tramos predeterminados). El nombre
indica el rango de precio. Los objetivos previstos y la consigna propuesta
continúan como sensores diagnósticos separados, no mandos falsos.

Estas entidades y **Configurar → Splits → Temperaturas por precio** comparten
el mismo perfil persistente. Editar una celda crea una excepción de esa zona;
los demás tramos siguen heredando cuando no tienen excepción. El formulario
permite volver a la tabla común. Un objetivo externo configurado tiene la
autoridad y deja sus números de tabla no disponibles para evitar ajustes sin
efecto; se cambia la fuente o se retira su binding en Configurar.

Se rechazan valores no finitos/fuera de5–35°C y calor≥frío en cada fase/tramo,
sin guardar medias configuraciones. Los cambios sucesivos de objetivos no
descargan las plataformas: se aplica el perfil validado, revoca decisiones
antiguas y solicita la revisión normal, preservando Manual, memoria y fuentes.
Los demás cambios de configuración conservan su recarga nativa habitual.

**En observación, editar objetivos solo cambia propuestas.** No activa la
ejecución ni modifica la consigna física. En modo control autorizado, orienta
la siguiente revisión con todas sus guardas; no es un servicio directo al AC.
Humedad, horarios, prioridad, fuentes, consumos y límites de modulación se
ajustan en los cinco grupos de Configurar, sin necesidad de editar YAML.

### Ruido de cero del medidor

**Consumo/medidores → medidor → Tolerancia a ruido negativo (W)** es opcional,
predeterminada0 (estricta), máximo20W. Solo para un medidor conocido de consumo
unidireccional con pequeño error alrededor de cero: dentro del margen se lee0W;
fuera se mantienen datos inválidos. No usar para ocultar exportación real.
Se normalizan W/kW antes de comparar. El sensor original, el contador/estadísticas
de energía y el medidor independiente de protección general no cambian. La
tolerancia queda visible en los atributos del diagnóstico energético.
Volver a0 elimina el campo opcional del perfil, conservando el ID del medidor;
hacerlo antes de volver a una revisión que todavía no admite esta tolerancia.

## Casa, instalación y estancia

| Nivel | Campos y significado |
|---|---|
| Casa | Nombre, zona IANA, tarifa, horarios y política común. Una entrada por casa. |
| Instalación | Nombre, UUID estable, sentido compartido o independiente, mínimos de encendido/apagado, permanencia y separación entre inversiones. |
| Estancia | Sensor ambiental, humedad opcional, `climate` opcional, autorización opcional, instalación, prioridad, corrección, permiso de secado, horario nocturno, habilitación, área y etiquetas. |

Los UUID se crean una vez y se conservan al editar nombres o sensores. No se puede
asignar el mismo actuador a dos estancias dentro de una entrada. No hay borrado
de estancias en la alfa: deshabilitar conserva identidad e histórico. Para varias
entradas, evitar duplicar una misma casa; el ejecutor0.2 aplica bloqueo
global de actuador antes de permitir control.

`authority_entity` puede ser un ayudante, selector o señal nativa; los valores
que conceden automático se eligen con `authority_states` (por defecto `on`).
Desconocido/indisponible nunca concede permiso. Sin selector externo, la
candidata de control usa además su interruptor nativo de autoridad por estancia.
`control_entity` es el permiso global con estados permitidos configurables;
si está asignado y falta/falla, pausa. En `control` es obligatorio. En `shadow`
pausar propuestas no equivale a un apagado físico.
`presence_entity` es una señal nativa con `presence_states` explícitos, también
puede ser `person`/grupo/schedule. No se reasignan trackers ni se infiere una
ubicación fiable por el nombre de una entidad. Véanse las fuentes opcionales,
objetivos externos y medidores en [EXECUTION_ENERGY.md](EXECUTION_ENERGY.md).

Áreas y etiquetas se seleccionan del registro nativo. No se crean áreas falsas.
Las etiquetas se añaden sin borrar las personales. Los cambios posteriores de
metadatos no eliminan automáticamente etiquetas anteriores.

## Tarifas

| Tipo | Entrada | Reglas |
|---|---|---|
| PVPC | Sensor nativo HA | Valor actual y atributos `price_XXh`, `price_next_day_XXh`, repetición `_d`; EUR/kWh. Se exige coherencia del tramo actual. |
| Plana | Precio numérico | EUR/kWh; puede ser cero o negativo. No representa la factura completa. |
| Fija por tramos | Días, inicio, fin, precio y fecha opcional | Cobertura semanal completa, sin solapes; admite madrugada. Una fecha sustituye los minutos coincidentes del patrón semanal. |
| Genérica | Sensor con `intervals` | Cada fila contiene `start`, `end` ISO con zona y `price`; unidad EUR/kWh o EUR/MWh (también símbolo €). |

En tramos fijos lunes=0, domingo=6; la interfaz traduce los días. Inicio=fin
representa 24 horas desde esa hora. Un tramo 22:00–06:00 pertenece al día de su
inicio, también al usar excepción por fecha. Las fechas especiales no convierten
automáticamente festivos: se configuran. Para mover varias fronteras, usar
**Cambiar tipo/reconstruir tarifa** y terminar una nueva tabla válida; el borrador
no sustituye la tarifa anterior hasta estar completo. Editar una fila exige que
la tabla siga siendo válida de inmediato.

Internamente todos los intervalos son UTC, con fin excluido. Días de 23/25 horas
se recorren realmente; no se duplica ni inventa precio. Si falta un tramo futuro,
la previsión se detiene ahí. Precio desconocido activa diagnóstico y usa el
objetivo de confort de la banda `normal`, sin programar secado oportunista como
si fuera gratis. Humedad urgente conserva sus protecciones térmicas.

No usar precio mayorista como si fuese PVPC final. `negative` significa **precio
de la señal menor que cero**, no factura total negativa.

## Bandas y objetivos

Fronteras exclusivas por arriba; son editables en Opciones:

| Banda | EUR/kWh por defecto | Calor día/noche °C | Frío día/noche °C | HR inicio/fin |
|---|---|---|---|---|
| negative | <0 | 21 / 19,5 | 24 / 25 | 65 / 60 |
| very_low | 0–<0,05 | 21 / 19,5 | 24 / 25 | 65 / 60 |
| low | 0,05–<0,10 | 20,5 / 19 | 25 / 26 | 65 / 60 |
| normal | 0,10–<0,20 | 19,5 / 18,5 | 26 / 27 | 65 / 60 |
| high | 0,20–<0,30 | 19 / 18 | 27 / 28 | 65 / 60 |
| very_high | ≥0,30 | 18,5 / 18 | 28 / 28 | 65 / 60 |

Son valores iniciales editables, no prescripción de confort ni regla certificada
para una vivienda. La candidata permite cuatro tablas por estancia y banda:
**calor día, frío día, calor sueño y frío sueño**, con herencia independiente de
la política común y validación de compatibilidad calor/frío. Franjas: laborable 07–22,
fin de semana empieza09; viernes/sábado terminan23. Se editan cuatro horas;
no hay todavía calendario de vacaciones ni tres fases nocturnas.

La estructura admite, por ejemplo, HR 60/55 en barato y 65/60 en normal. No viene
activado por defecto: bajar umbrales sin capacidad de quitar agua puede crear
demanda permanente. Nunca eliminar la deuda/urgencia al cambiar de banda.

## Regulación térmica

| Parámetro | Inicial | Interpretación |
|---|---|---|
| `start_delta` / `hold_delta` / `overshoot_delta` | 0,5 / 0,2 / 0,5 °C | Arranque, mantenimiento, protección por exceso. |
| `proportional_gain` / `boost_limit` | 0,7 / 1 °C | Esfuerzo transitorio proporcional y limitado. |
| `correction_limit` / `bias` | 6 °C / 0 por estancia | Tope combinado y corrección estable del sensor interno. |
| `command_interval` | 300 s | Cadencia mínima entre órdenes ordinarias; no es la frecuencia de cálculo. En observación no se emite ninguna. |
| Instalación: mínimo off/on | 1200 / 1200 s | Evitar ciclos cortos, salvo protección por exceso. |
| Permanencia / separación inversión | 3600 / 7200 s | Restricciones de sentido compartido. |

Consigna propuesta = objetivo ambiental + corrección estable + esfuerzo acotado;
se redondea al paso y límites del equipo. Cerca del objetivo se retira esfuerzo y
se permite alivio referido al sensor interno reciente. **No es aprendizaje PI ni
una calibración automática.** Cuando el sensor del split difiere, poner siempre
su consigna igual al Aqara no asegura mantener la temperatura ambiental.

El planificador ordinario completo se recalcula como máximo cada **300 s**;
actualizaciones de fuentes no críticas se agrupan dentro de ese intervalo. No se
usa un `delay` en el camino de seguridad: cambios de autoridad, Manual, equipo,
lecturas no disponibles y permisos urgentes conservan revisión reactiva. Si una
decisión trae un `next_at` anterior, se agenda un despertar puntual para ese
plazo; el intervalo de órdenes sigue siendo una guarda distinta. Véase
[cadencia de planificación](PLANNING_CADENCE.md).

Ya estar en modo/consigna correctos significa mantener, no una nueva orden.
No se introduce `fan_only` como paso económico rutinario. No se puede deducir un
ciclo del compresor de un cambio de modo HA.

### Mantenimiento modulado y corte económico opcionales

Las dos estrategias siguientes vienen **desactivadas** y siguen siendo propuestas
sin órdenes. Las bandas de objetivos por precio continúan siendo la referencia.

| Parámetro | Inicial | Significado |
|---|---|---|
| `modulated_hold_s` | 0 | Duración máxima propuesta con consigna relajada; 0 desactiva, máximo7200s. |
| `extreme_price_enabled` | false | Modelar corte económico ante precio extremo. |
| `extreme_price` / `extreme_price_hysteresis` | 0,30 / 0,02 EUR/kWh | Entrada y margen de salida del tramo extremo; no son valores certificados para una vivienda. |
| `thermal_stable_s` | 900s | Estabilidad mínima sustentada en informes distintos de la sonda. |
| `thermal_stability_delta` | 0,3°C | Rango máximo de temperatura de esa secuencia estable. |
| `thermal_sample_gap_s` | 1200s | Hueco máximo entre evaluaciones e informes para no reiniciar continuidad. |

En espera se mantiene el sentido ya activo, sin arrancar una cabeza apagada.
Calor reduce su consigna y frío la eleva, sin aumentar la exigencia frente a la
consigna observada y con sonda interna fresca. Se retira el empuje, no se fuerza
el número del Aqara como consigna física universal. Se conserva el presupuesto
de espera al recargar; un cambio de precio no lo renueva por sí mismo. Al agotar
la espera propone off, respetando el mínimo de marcha. Déficit real retoma
regulación; sobrepaso protector conserva prioridad. Manual/pausa invalidan la espera.

El corte económico requiere precio conocido, estabilidad medida y temperatura
dentro de la banda de confort activa. Un déficit impide cortar solo por precio.
Un informe repetido no acumula estabilidad; hueco, reloj regresivo o deriva
reinician la continuidad. El precio debe bajar del umbral menos su margen para
liberar el estado extremo. No se salta el mínimo de marcha por tarifa sola.

`holding` significa **propondría una consigna relajada**: no es un modo standby
nativo, reserva aceptada, potencia cero ni ahorro medido. Todavía no se estima
la inercia futura ni el coste de recuperación; compararlos sigue siendo requisito
de validación del ejecutor y del ensayo por vivienda.

## Humedad y ventanas útiles

Primero se resuelve demanda térmica y la instalación compatible. Después se
considera secar si hay permiso, capacidad, exterior válido y margen ambiental.
El suelo de secado no aumenta al subir el objetivo térmico por precio.

| Parámetro | Inicial |
|---|---|
| `dry_floor_day` / `dry_floor_sleep` / `dry_margin` | 20 / 19 / 1 °C |
| `dry_min_outdoor` | 10 °C |
| `dry_min_s` / `dry_max_s` | 1200 / 1800 s |
| `dry_cooldown_s` / `dry_attempts` | 14400 s / 2 al día local |
| `humidity_stable_s` / `humidity_recovery_s` | 900 / 600 s |
| `service_humidity` / `humidity_deadline_s` | 65 % / 14400 s |
| `urgent_humidity` / `urgent_stable_s` | 75 % / 1800 s |
| `severe_humidity` / `severe_stable_s` | 80 % / 900 s |
| `lookahead_s` / `improvement` | 5400 s / 0,04 EUR/kWh |

Se compara el coste medio ponderado del **bloque completo de duración máxima**,
no solo su primer minuto. Si otro bloque cercano mejora el precio suficientemente,
se espera; urgencia/deuda evita aplazar indefinidamente, pero no salta seguridad.
Una sesión propia aceptada conserva máximo absoluto, suelo y presupuesto aun
con precio/sensor/pausa cambiantes. Manual cancela la propiedad del planificador,
no borra intentos consumidos. La alfa no adopta sesiones `dry` ajenas.

## Calidad de datos y potencia

Temperatura/humedad ambientales recientes ≤7200s por defecto, interna≤600s,
potencia≤120s; se pueden configurar. La antigüedad usa `last_reported`, no solo
cambio de valor. Un sensor ambiental que no reporta durante dos horas bloquea
esa estancia, no toda la casa. Temperatura °C/°F, HR %, potencia W/kW; VA no sirve.

`power_limit` inicial6000W. Sin contador seleccionado no hay guardia de potencia;
con contador seleccionado pero inválido se bloquean incrementos, no reducciones
seguras. Es un límite de propuesta agregado, **no** una protección eléctrica
certificada ni un reparto de W medidos por split. No se inventa consumo por zona.

Los parámetros avanzados se editan en **Política**; todos tienen validación de
rango y las relaciones principales se verifican juntas. Restablecer selectores
opcionales elimina el vínculo; no conserva silenciosamente el sensor anterior.

## Asignaciones energéticas y actuación opcional

La candidata0.2 añade los menús Medidores energéticos y Ejecución, y fuentes
externas por estancia. Contrato completo y límites en
[EXECUTION_ENERGY.md](EXECUTION_ENERGY.md).

## Objetivos por split, estación y precio

En **Objetivos por estancia** selecciona el split y una de cuatro tablas:
calor/día, frío/día, calor/sueño o frío/sueño. Cada fila corresponde a un tramo
de precio. Puedes heredar la tabla general o activar una propia sin cambiar
las otras tres. Los tramos ausentes en un perfil JSON se heredan.

Las claves son `heat_targets` (calor/día, compatible con perfiles anteriores),
`cool_targets`, `heat_sleep_targets` y `cool_sleep_targets`. Una fuente externa
de objetivo válida tiene precedencia. Si está asignada pero ausente, bloquea
la zona: no se sustituye silenciosamente por la tabla. Se rechaza calor ≥ frío
en cualquier fase/tramo. `priority` resuelve demanda competidora, no reparte
vatios del medidor.

Una **planta** representa la unidad exterior física, no la planta del edificio.
`shared_mode: true` coordina sus cabezas en un único sentido y conserva los
mínimos de marcha, reposo e inversión. Los equipos independientes se asignan
a plantas independientes y pueden calentar/enfriar simultáneamente.

## Modulación continua opcional · candidata 0.2

`continuous_hold: true` mantiene una cabeza ya activa y autorizada en calor/frío
al alcanzar confort, sin plazo rutinario de apagado ni `fan_only` económico.
No arranca un aparato satisfecho solo para mantenerlo encendido. El objetivo
ambiental sigue la tabla/precio; la consigna física utiliza sesgo, déficit,
respuesta ambiental y relajación progresiva. La sonda interna puede relajar
la demanda cerca del objetivo, nunca se persigue la batería caliente para
aumentar potencia. El esfuerzo y la relajación requieren reportes ambientales
distintos: cada evaluación no fabrica aprendizaje.

`overshoot_delta` permite parar ante exceso aun antes del mínimo de marcha.
No cambia automáticamente: por defecto sigue en0,5°C; configura otro margen
explícitamente si el ensayo lo requiere. `relaxation_limit` acota la relajación
física (3,5°C por defecto), siempre dentro del paso y límites reales del equipo.

`shared_load_management: true` añade realimentación del **medidor de la unidad
exterior**, no del suministro. No suma padres/hijos ni divide potencia entre
cabezas. Un split independiente puede usar su medidor de zona cuando es el
único miembro de su planta y no hay medidor de planta. Dos medidores de potencia
competidores para el mismo ámbito no permiten inferir cuál debe gobernar.

Aprende referencias agregadas por número de cabezas activas. Solo propone retirar
**una** cabeza si todas las activas son automáticas, tienen confort satisfecho,
consignas relajadas, datos frescos y temperatura estable durante un episodio de
carga alta. La propuesta caduca90s después de publicarse, se revalida al ejecutar
y consume presupuesto por cabeza incluso si falla. Otra retirada requiere
observar el efecto y un nuevo episodio. Nueva demanda, objetivos, Manual, pausa,
datos ausentes o cambios de configuración invalidan la propuesta. Una diferencia
de potencia tras retirar servicio es agregada, no consumo causal de esa cabeza.

| Parámetro | Valor inicial |
|---|---:|
| `shared_load_idle_w` / `shared_load_high_w` |150/250W|
| `shared_load_observe_s` |1200s|
| `shared_load_retry_s` |7200s por cabeza|

Son editables en **Política**. Continuidad y gestión compartida vienen apagadas;
la segunda requiere continuidad.100W no es una orden al compresor ni una garantía:
depende del equipo y se comprueba con potencia activa medida. Manual, permisos
y corte independiente siguen limitando al controlador.

Ejemplo ficticio de multisplit más equipo independiente, prioridades y tablas:
[versatile-zones.json](../examples/versatile-zones.json). Sigue en sombra hasta
superar [la migración de autoridad](MIGRATION.md).

### Policy form ranges and zero values

The numeric policy form uses the same scalar bounds as `Policy` validation.
Cross-field constraints still apply: hold < start, overshoot > hold, shared-load
high > idle, extreme-price exit margin < entry, and a nonzero drying maximum
must be at least its minimum. A form range alone does not relax these relations.

`dry_max_s = 0` means **no absolute split-drying session deadline**. The accepted
session keeps its endpoint and ownership; thermal, source, Manual, permission,
plant and fault/ACK protections still apply. Economic-window estimation uses
`dry_min_s` for an uncapped session, not an infinite forecast horizon. Independent
dryers use their separate `dehumidifier_max_s` setting (also 0 = unlimited).
`modulated_hold_s = 0` instead disables the proposed soft hold; zero is not a
universal "off" switch. No existing values or control authority are migrated by
this form correction.

Read [autonomy readiness](AUTONOMY_READINESS.md) for configuration principles,
remaining usability work and the acceptance gates before household handover.
