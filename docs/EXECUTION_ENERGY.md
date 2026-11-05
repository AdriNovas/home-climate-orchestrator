# Ejecución y asignación energética · candidata 0.2

La versión pública 0.1 continúa siendo observadora. Esta rama 0.2 añade un
ejecutor separado y opcional: una entrada existente **no empieza a controlar por
actualizarla**. El modo predeterminado sigue siendo `shadow`.

## Asignaciones, no nombres de una vivienda

En **Opciones → Fuentes** se seleccionan permiso global, ocupación, exterior,
potencia total del suministro y, opcionalmente, señal de corte crítico externo.
Los estados que significan permiso/ocupación son configurables; no se presupone
que todo el mundo utilice `input_boolean` ni los valores «IA»/«Manual».

En **Opciones → Estancia** pueden asignarse:

| Campo | Significado |
|---|---|
| `climate_entity` | Equipo ya integrado en HA, con estado y capacidades reales. |
| `temperature_entity`, `humidity_entity` | Referencia ambiental y humedad opcional. |
| `authority_entity`, `authority_states` | Autoridad externa y estados que conceden automático; también admite selectores. |
| `permission_entity` | Permiso operativo de estancia; `on` permite, dato ausente/desconocido bloquea. No equivale a ceder Manual. |
| `heat_permission_entity`, `cool_permission_entity`, `dry_permission_entity` | Permisos externos por modo: estación, calendario, ventanas o reglas propias; `on` permite. |
| `heat_goal_entity`, `cool_goal_entity` | Objetivos ambientales externos que sustituyen la matriz cuando están asignados. |
| `bias_entity` | Desfase interno menos referencia, no una consigna física. Admite ayudantes numéricos con unidad explícita. |
| `internal_entity` | Sonda interna separada cuando no se usa el atributo del climatizador. |

Sin asignar un objetivo externo se utiliza la matriz propia. Si **está asignado
pero falla**, no se vuelve silenciosamente a otra política. Los objetivos y el
desfase deben tener unidades y disponibilidad válidas. Los sensores exigen
frescura; `input_number`/`number` representan ajustes persistentes y no se
convierten en medidas caducadas por no haber cambiado; las medidas absolutas °F se
convierten a °C y los desfases °F se convierten como diferencias, sin restar32.
Los valores del núcleo están en °C; las órdenes vuelven a la unidad nativa de HA.

Estas entradas permiten conservar horarios de varias fases y política estacional
propios mediante sensores/helpers nativos, sin copiarlos al producto. Asignar
solo los objetivos **no reproduce todas las guardas** de una instalación: también
hay que vincular sus permisos y certificar la matriz de autoridad y emisores.

## Medidores y consumo

**Opciones → Medidores energéticos** permite añadir, editar y retirar asignaciones.
Cada medidor tiene UUID estable y un ámbito real: vivienda, instalación compartida
o estancia. Se pueden usar entidades de cualquier integración que publiquen:

- Potencia activa instantánea en `W` o `kW`.
- Contador acumulado en `Wh`, `kWh` o `MWh`.
- Ambas, o solo una. La falta de energía acumulada no obliga a inventarla.

Se publican potencia normalizada, energía y, si hay precio conocido, **coste
instantáneo = kW × precio actual**, en EUR/h. No es coste acumulado, factura,
ahorro, COP ni potencia de compresor por modo HVAC. El precio no incluye
automáticamente impuestos ni términos fijos de una tarifa real.

La antigüedad máxima de potencia (`fresh_s`) y energía (`energy_fresh_s`) se
configura por separado: un contador que informa cada hora no debe degradarse
porque la potencia se vigile a120s. Unidades ambiguas, VA/kVA, negativos de un
medidor neto, NaN e infinitos no se interpretan como consumo cero.

Un multisplit con un contador común tiene **un medidor de instalación**, no uno
por cabeza. Se rechaza asignar el mismo sensor a varios ámbitos. No se suman
automáticamente medidores de vivienda y sus hijos: se contarían dos veces.
No se reparte consumo agregado entre habitaciones. Para consumo por estancia
hace falta medición real a esa escala.

Las fuentes originales, sus `unique_id`, contadores y estadísticas no se escriben,
renombran, reinician ni purgan. Los sensores de esta integración son espejos
diagnósticos nuevos; las series originales siguen siendo la referencia del panel
Energía. Retirar una asignación solo retira el vínculo y sus entidades propias.

## Activación explícita y protocolo

**Opciones → Ejecución** permite elegir `control`, con permiso global asignado y
confirmación de que se han detenido los otros controladores de esos equipos.
La integración impide que dos entradas activas suyas posean el mismo actuador;
no puede deducir si una automatización ajena también lo controla.

1. Serializa las transacciones de cada instalación; instalaciones independientes
   pueden progresar simultáneamente. Coalesce revisiones en lugar de acumularlas.
2. Captura una generación de autoridad, relee estado/plan al obtener turno y
   persiste intención identificada antes de emitir.
3. Registra las transiciones esperadas. Si hay cambio de objetivo, lo confirma
   antes de cambiar modo; revalida permisos tras cada espera/escritura.
4. Confirma por **estado observado**, no por el retorno del servicio. Una orden
   sin confirmación queda incierta y bloquea nuevos arranques; no se reintenta
   a ciegas. Un reinicio tampoco repite un arranque interrumpido.
5. Una orden humana no coincidente o con contexto explícito retira autoridad
   local. El interruptor nativo por estancia permite rearmar; sigue exigiendo
   permisos externos. Un eco antiguo no borra Manual ni amplía su vigencia.
6. El secado propio persiste inicio, máximo absoluto, suelo y presupuesto antes
   de emitir. Tiene salida independiente al vencer o perder margen/datos,
   también durante pausa; no adopta un secado de otra autoridad.

Un retorno tardío ya transmitido **no se puede destransmitir**. Se reconcilia el
estado, se conserva la incertidumbre y, durante corte crítico, se vuelve a pedir
off. No se ofrece semántica exactly-once ni protección autónoma si HA está caído.
Un controlador físico sigue siendo responsable de sus protecciones locales.

## Protección eléctrica y alcance

`power_entity` de Fuentes es el **suministro total**, independiente de los medidores
de consumo del clima. El presupuesto preventivo del núcleo limita nuevas demandas
y permite reducciones. La protección crítica tiene umbral/duración e histéresis
configurables; requiere informes distintos y continuidad, no repetir una lectura.
Sin dato válido no libera un corte retenido. También puede consumir una señal
externa `critical_entity` (`on` corta, `off` permite evaluar recuperación).

El corte persiste una nueva generación antes de despachar apagados por estancia,
en paralelo y sin esperar la cola/ACK ordinarios. Puede parar Manual: **solo** los
`climate_entity` explícitamente asignados. No gobierna enchufes, contactores,
termos ni cargas ajenas. No se libera mientras haya emisión ordinaria en vuelo o
algún equipo asignado siga sin confirmar off.

## Compatibilidad y límites comprobables

Los ensayos usan un HA vacío y servicios simulados. No certifican que una marca
concreta confirme su estado, que cambiar consigna estando apagada no arranque la
máquina, ni que un emisor IR tenga retorno real. Estos requisitos se verifican
por instalación antes de activar. No hay adaptador de contactor o válvula binaria.
El núcleo prioriza confort e histéresis; todavía no aprende un modelo térmico,
predice coste de recuperación ni demuestra que mantener supere siempre a apagar.

Contrato de migración y reversión: [MIGRATION.md](MIGRATION.md).
Ejemplo ficticio: [shared-meter.json](../examples/shared-meter.json).
