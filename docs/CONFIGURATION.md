# Configuración · esquema 1

Toda la configuración operativa está en la entrada de integración y sus opciones;
no hay que editar constantes Python ni rellenar entidades de una casa concreta.
Los perfiles JSON de `examples/` documentan el esquema interno; **no existe
importador JSON en la interfaz de la alfa**.

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
para una vivienda. Opciones permite objetivos de calor **diurnos** por estancia y
banda; noche/frío siguen la matriz común en esta alfa. Franjas: laborable 07–22,
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
| `command_interval` | 300 s | Cadencia mínima entre órdenes; en observación no se emite ninguna. |
| Instalación: mínimo off/on | 1200 / 1200 s | Evitar ciclos cortos, salvo protección por exceso. |
| Permanencia / separación inversión | 3600 / 7200 s | Restricciones de sentido compartido. |

Consigna propuesta = objetivo ambiental + corrección estable + esfuerzo acotado;
se redondea al paso y límites del equipo. Cerca del objetivo se retira esfuerzo y
se permite alivio referido al sensor interno reciente. **No es aprendizaje PI ni
una calibración automática.** Cuando el sensor del split difiere, poner siempre
su consigna igual al Aqara no asegura mantener la temperatura ambiental.

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
