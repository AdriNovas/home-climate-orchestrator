# Estrategias y actividad opcional · candidata de desarrollo

Esta capacidad no se instala ni se activa al actualizar. La publicación y los
pilotos físicos son entregas distintas del código y de las pruebas aisladas.

## Un motor, cuatro claves estables

| Selección | Demanda térmica ordinaria |
|---|---|
| `legacy` · Anterior | Conserva las tablas por precio y los consumidores existentes. Predeterminada si una entrada antigua no declara estrategia. |
| `comfort` · Confort | Persigue la preferida; no aplaza una demanda por una ventana de precio. |
| `balanced` · Equilibrado | Puede usar la mitad de la flexibilidad autorizada y una espera más corta. |
| `price` · Precio | Puede usar toda la flexibilidad autorizada y una espera mayor. |

Los tres perfiles nuevos parten de la temperatura **preferida**, no de la tabla
de la franja cara. Puede elegirse por habitación y día/sueño. Si se deja vacía,
hereda la tabla normal del usuario (o la central si no hay banda llamada normal).
Los objetivos externos vinculados siguen siendo autoritativos: el perfil no
reescribe esas entidades ni modifica sus consignas.

**Flexibilidad y ajustes por ausencia empiezan en cero.** Sin concesiones explícitas
es normal que las tres estrategias produzcan la misma decisión. Precio no es una
promesa de ahorro; Confort no garantiza una temperatura que el equipo no alcance.

### Espera y recuperación

Una espera térmica requiere todo lo siguiente:

- Equipo apagado, demanda real y temperatura dentro del margen autorizado.
- Bloque de tarifa actual completo y otro completo más barato, sin huecos.
- Oportunidad dentro de la espera máxima y del horizonte configurado.
- Presupuesto de desviación medida no agotado; se acumula solo con muestras
  distintas y ordenadas, sin interpolar interrupciones largas.

No se precalienta por el mero hecho de que el precio sea cero o negativo. Si
falta tarifa/previsión, se recupera la preferida sin inventar oportunidades.
El plazo reservado solo puede acortarse; cambiar de perfil no lo renueva.
Una nueva espera económica activa se persiste antes de publicar la concesión,
sin depender únicamente del checkpoint diferido de observaciones.
Salir de la banda o agotar el plazo vuelve a regulación normal. La ejecución
seguirá teniendo sus permisos, compatibilidad, protecciones y cadencia reales.
El recálculo sigue siendo coalescido; no se promete una orden en el segundo
exacto de vencimiento ni saltarse la cadencia del equipo.

La humedad es un servicio separado. Los nuevos perfiles solo pueden aplazar
una demanda no urgente hasta una ventana completa dentro de su plazo. La
ausencia de precios elimina esa optimización, no el servicio. Un ciclo propio
conserva objetivo de humedad, suelo, intentos y máximo absoluto, incluso al
cambiar de estrategia. No se añade precarga→espera→dry en esta entrega.

## Configuración nativa y autoridad

En **Configurar → Confort y horarios → Estrategia** se elige la preferencia.
Un `select` de categoría Configuración permite cambiarla sin descargar entidades.
Las entradas nuevas sugieren Equilibrado, pero siguen empezando en observación.

Hay dos puertas independientes:

1. El ejecutor debe estar previamente habilitado, autorizado y ser exclusivo.
2. **Aplicar al ejecutor** debe estar activado expresamente.

Si no se cumplen ambas, los objetivos anteriores siguen usando `legacy` y cada
estancia publica las tres alternativas en **Comparación de estrategias**. Esta
salida separada no es una simulación física ni un histórico del confort que
habría causado otro perfil. No altera objetivos enlazados, contabilidad,
propiedad o journal. Tampoco impide que alguien cree posteriormente una
automatización que actúe al leerla: revisar consumidores antes de activar.

Elegir un perfil no habilita ejecución, no llama al preset del fabricante,
no cancela Manual y no adopta sesiones ajenas. Las ediciones de preferencias y
tablas se aplican en caliente; cambiar fuentes o topología requiere recarga.
Las intenciones de una revisión anterior se invalidan antes de publicar metas.

## Presencia, movimiento y otras señales por habitación

**Configurar → Equipos y sondas → Habitación → Presencia y actividad** admite
cero, una o varias entidades HA. No se obliga a comprar sensores ni se exige
Zigbee, mmWave, un fabricante o una clase de entidad concreta.

| Semántica elegida | Qué significa |
|---|---|
| Presencia | Un estado positivo confirma ocupación; uno negativo explícito puede confirmar ausencia tras su retardo. |
| Movimiento | Un pulso positivo conserva actividad durante el tiempo elegido. `off` o silencio no prueban que la habitación esté vacía. |
| Otra actividad | Igual evidencia positiva temporal, con estados configurables: por ejemplo `working`/`idle` o `playing`/`off`. |

Los estados son explícitos y disjuntos; `unknown`/`unavailable` no son estados
positivos o negativos válidos. La fusión aplica:

1. Una fuente positiva o un pulso aún vigente prevalece sobre otras negativas.
2. Para afirmar **vacía**, todas las fuentes de **presencia** configuradas deben
   confirmar ausencia; los PIR no votan en negativo.
3. Sin evidencia suficiente, el resultado es **desconocida**, no vacía.

Los pulsos se capturan en el listener para no perderlos entre dos recálculos.
La memoria conserva su marca original: reiniciar, editar un atributo o volver a
publicar la caché no amplía el plazo. Los estados HA marcados como restaurados
no crean evidencia nueva. Sin reloj de origen explícito, se conoce la transición
recibida en HA, no necesariamente el momento físico del sensor.

La edad máxima opcional comprueba el reloj configurado. Cero conserva la
semántica de disponibilidad del proveedor; no implica certificación de frescura.
Con contrato de origen, un timestamp ausente o futuro no aporta evidencia válida.
Un sensor averiado puede conservar una evidencia positiva anterior hasta su
vencimiento, pero nunca aportar una nueva confirmación negativa.

Los ajustes por habitación vacía son opt-in, acotados por mínimo de calor y
máximo de frío, e independientes de la estrategia. Ocupada o desconocida usa
las preferencias ordinarias. No apagan automáticamente la habitación, no
cambian autoridad ni el permiso global de presencia, y no obligan a cortar
humedad. El antiguo `thermal_presence_entity` sigue siendo un **permiso
explícito** diferente, no una fuente del nuevo detector.

No se interpreta un detector de puerta como presencia ni se crean umbrales
numéricos implícitos. Para una señal continua, el usuario puede vincular un
sensor binario derivado con el significado deseado. La estructura permite
añadir adaptadores explícitos sin incrustar reglas de una vivienda.

## Calidad de fuentes

En **Fuentes y funcionamiento → Origen de las medidas** se pueden declarar
contratos opcionales por entidad:

```json
{
  "sensor.room_temperature": {
    "semantics": "origin",
    "timestamp_attribute": "sampled_at"
  },
  "binary_sensor.room_presence": {
    "semantics": "origin",
    "timestamp_entity": "sensor.room_presence_timestamp"
  }
}
```

Es un ejemplo ficticio; no hay importación automática de perfiles domésticos.
El timestamp es Unix en segundos o ISO8601 con zona. Solo se elige una ruta.
`received` (respaldo compatible) utiliza recepción HA sin afirmar una medición
nueva; `provider` declara una garantía del proveedor; `origin` exige la marca
explícita y no recurre a recepción si falla. Una marca del mensaje no garantiza
que el dispositivo haya medido nuevamente: el contrato debe describir la fuente.
Los ajustes numéricos persistentes no caducan como un termómetro físico.

Los relojes de origen ausentes, inválidos o futuros abren **una incidencia
agrupada en Repairs** por entrada, sin push ni destinatarios incrustados. Se
retira al recuperar marcas válidas. Una lectura antigua con reloj válido sigue
mostrándose caducada en la decisión del ámbito afectado. No se reinician radios.

## Monedas y compatibilidad

La moneda se declara al crear la entrada. PVPC sigue siendo EUR. El adaptador
genérico admite `USD/kWh`, `GBP/MWh`, `EUR cents/kWh`, etc., con unidades
explícitas coherentes; rechaza unidades ambiguas, mezcla de monedas y solapes.
Los umbrales monetarios siguen siendo configurables en la moneda elegida: no
se aplica conversión FX ni se presentan los umbrales EUR como presets mundiales.

Los sensores de coste usan la moneda declarada, separados de energía. Cambiar
la moneda de una entrada con ledger **se rechaza sin sobrescribirlo**. La
conversión/migración monetaria dentro de una entrada no está implementada: se
requiere una entrada independiente y conservar la anterior para sus históricos.
Los medidores originales y sus estadísticas nunca se reescriben.

El núcleo y el adaptador convierten °C/°F y diferencias por rutas distintas;
los formularios avanzados de preferencias indican explícitamente °C. No es aún
un formulario localizado de temperaturas en °F. La certificación física de
termostatos solo calor, calderas, suelos radiantes y otras topologías sigue
pendiente: no basta con que el formato de una entidad sea compatible.

## Persistencia, actualización y reversión

La configuración nueva declara `strategy_schema: 1`; una versión futura
desconocida se rechaza. La selección se guarda en las opciones nativas; Manual,
ACK, propiedad y generaciones continúan en el journal existente.

Los campos nuevos de actividad/esperas se guardan en `strategy_memory`, separados
de las antiguas filas `zones`. Así la versión precedente no rechaza por campos
extra la memoria de intentos, deuda y sesiones. Un esquema nuevo incompatible o
una moneda conflictiva no se sobrescriben al fallar la carga. Esto no hace que un código antiguo entienda la
configuración nueva: **downgrade no equivale a copiar ficheros viejos**.

Reversión operativa: desactivar la aplicación del perfil primero; invalidar y
reconciliar órdenes emitidas y sesiones propias; conservar copia de configuración,
journal y ledger; comprobar el esquema de la versión destino. Restaurar una
configuración compatible de observación, sin retirar guardas de origen para
reactivar control antiguo. Retomar autoridad requiere inventario del escritor
único y validación de ese controlador. No se ha desplegado ni ensayado esta
reversión en una vivienda real.

## Límites de esta entrega

- Núcleo y protocolo HA probados con equipos ficticios; no son evidencia física
  de ahorro, secado, temperatura alcanzada o compatibilidad universal.
- No se añade modelo energético, precarga térmica, refuerzo temporal, vacaciones
  avanzado, autoconsumo, carbono o aprendizaje autónomo de preferencias.
- Persisten los horarios configurables día/sueño y permisos explícitos de la
  instalación. La actividad local no redefine la presencia global de la casa.
- El siguiente gate es revisión/preview con fuentes reales y consumidores, y
  después un piloto de escritor único por topología certificada.

Referencias nativas: [SelectEntity](https://contributors.home-assistant.io/core/entities/select/)
y [opciones](https://contributors.home-assistant.io/core/integrations/options-flow/).
