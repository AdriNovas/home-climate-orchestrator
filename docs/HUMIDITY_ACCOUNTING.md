# Humedad y consumo medido

## Objetivos por estancia y precio

Cada zona tiene tablas independientes de **iniciar secado** y **terminar secado**,
por banda de precio. Están en el menú de objetivos de su equipo y como entidades
`number` nativas (%), con la misma validación y persistencia. El fin debe ser
inferior al inicio. Una tabla vacía hereda los umbrales comunes de la tarifa.
Los objetivos de calor/frío conservan sus tablas de día/sueño.

En **Objetivos → Humedad por precio**, elegir un rango y editar los dos
porcentajes juntos. El formulario rechaza fin≥inicio sin guardar cambios
parciales. «Volver a los valores comunes» retira ambos overrides de ese rango,
sin alterar otros precios. Las entidades number siguen siendo celdas reales
del mismo perfil.

Los umbrales no son límites sanitarios ni predicciones de HR. La humedad
persistente y urgente vence el aplazamiento económico, pero nunca Manual,
pausas, falta de sondas, suelo térmico o protecciones. Si no existe secado
viable, el sensor de servicio pendiente muestra el bloqueo. Una calefacción
encendida no demuestra extracción de agua.

Al aceptar una sesión se congela su objetivo de fin, suelo y vencimiento.
Cambiar de precio no renueva el máximo ni el presupuesto. No se adopta una
sesión manual. El punto de rocío solo se publica con temperatura y humedad
frescas; ayuda a distinguir calentamiento de reducción de vapor, pero no mide
litros ni demuestra qué aparato causó el cambio.

## Deshumidificador independiente

**Configurar → Equipos y sondas → Vincular deshumidificador** enlaza una entidad
`humidifier` cuya clase sea `dehumidifier` (extrae agua), temperatura ambiental
y humedad independientes. Se rechaza un humidificador que añade agua.
Se crea su propia instalación sin sentido compartido: puede secar mientras
otra instalación calienta. No se presupone que seque habitaciones cerradas.

El alta empieza pausada salvo selección explícita. Su menú avanzado permite
habilitación/permisos/Manual, mínimo y máximo de sesión, reposo y rango térmico
del fabricante. Predeterminados conservadores:10min mínimo/90min máximo,
20min reposo,10–32°C; no son una homologación de cualquier modelo.
Al alcanzar el máximo o detectar apagado externo, no reinicia el mismo episodio
hasta recuperar el umbral bajo. Se respeta el humidistato y sus protecciones;
`on` no equivale a compresor funcionando.

El adaptador usa `humidifier.set_humidity`, confirma el objetivo y después
`humidifier.turn_on`; nunca cicla mediante un enchufe. Los ecos de objetivo y
encendido se confirman con registro persistente. Fallo/ambigüedad o cambio
humano retira autoridad local. `turn_off` conserva un carril de protección.

### Referencia local o demanda de toda la casa

Un deshumidificador independiente puede usar su humedad local (`room`) o la
mayor lectura válida de las estancias configuradas (`home_max`). El agregado
solo se publica cuando **todas** las sondas configuradas están dentro del
límite de frescura y entre 0–100 %; la edad efectiva es la de la lectura más
antigua. Así se evita que una habitación con sensor caído desaparezca del
máximo o que un dato retenido provoque servicio indefinido. Una referencia no
disponible bloquea nuevas decisiones de humedad hasta recuperar fuentes frescas.

La disponibilidad `always` elimina únicamente las condiciones de presencia y
franja nocturna. No equivale a funcionamiento continuo: el motor sigue
respetando umbral de inicio/parada, permiso, pausa/Manual, rango térmico,
protección de depósito, reposo, disponibilidad del humidistato y límites de
carga. Un automatismo que consuma esta configuración debe replicar esas
protecciones de forma explícita; la integración no toma el control del actuador
por el mero hecho de publicar los valores.

## Calor ↔ dry: dos esperas distintas

El `dry` de un split enfría su batería. Al detenerse puede quedar condensado;
el aire circulando por la batería sin enfriamiento puede devolver parte de
esa humedad. No se usa `fan_only` rutinario como final de secado. Es un fenómeno
general documentado, no una medición del modelo concreto.
[FSEC/UCF](https://stars.library.ucf.edu/fsec/513/).

Cada instalación conserva mínimo encendido/apagado, estabilidad de sentido e
intervalo entre inversiones. Además configura **reposo/drenaje antes de volver
a calor** (5min predeterminados), independiente de las protecciones anteriores.
Se aplica la espera más larga. Ese intervalo **no garantiza una batería seca**,
no sustituye al manual y no autoriza ciclos calor→dry→calor. El deshumidificador
independiente no invierte el multisplit y entrega algo de calor al ambiente.
[ENERGY STAR](https://www.energystar.gov/products/dehumidifiers).

## Energía y euros por periodo

Cada medidor y el subtotal del sistema exponen kWh y EUR para **hoy, ayer,
semana, mes y año**. Se integran W activos medidos con cuadratura izquierda;
la lectura solo se mantiene hasta su límite de frescura. No se interpola una
caída/reinicio de HA. La energía acumulada original permanece como fuente de
consulta separada, sin modificarla, renombrarla ni reescribir Recorder.

Los euros se calculan con el precio publicado de cada intervalo UTC, incluidos
precios negativos. No se multiplica el precio actual por consumo pasado.
Falta de precio no borra kWh: deja coste parcial y kWh sin valorar. Los periodos
siguen la zona horaria doméstica, semanas desde lunes, meses/años naturales,
y días de23/25h. Los sensores usan `total`, no `total_increasing`, y publican
reinicio temporal para los cambios de periodo y base de medición.

**No se reconstruye el pasado.** Ayer anterior al alta figura desconocido,
no cero. Los atributos muestran inicio, cobertura temporal, integridad por
métrica y energía sin precio. Una cifra parcial es un subtotal conocido, no
una factura completa. Fuente/tarifa incluidas determinan impuestos; no se
añaden potencia contratada, alquiler u otros costes fijos.

Seleccionar explícitamente qué medidores entran en el subtotal. La validación
impide sumar una instalación y sus cabezas, dos medidores del mismo ámbito o
un padre de toda la vivienda con sus hijos. Un medidor excluido puede seguir
usándose para diagnóstico. El subtotal enumera zonas sin medición: no reparte
W compartidos por split ni inventa consumo de un aparato sin contador.
Los periodos requieren fuente de potencia; un contador de energía aislado no
proporciona por sí solo el reparto temporal del coste variable.

Los libros propios se conservan en la memoria versionada de la entrada.
Una nueva fuente/ámbito inicia nueva base y archiva la anterior, sin fingir
continuidad ni borrar estadísticas. Retirar la integración elimina solo su
memoria propia, no la del fabricante ni los sensores originales.

## Consumidores y configuración publicada

El sensor **Configuración efectiva del orquestador** publica una versión de
esquema, la política validada y los tiempos de cada instalación. Está destinado
a dashboards o consumidores de configuración expresamente conectados por el
administrador; no incluye credenciales ni registros de órdenes. Su estado
indica observación/control **configurado**, no que el compresor esté activo.
Leer esta superficie no concede permiso para controlar ni sustituye los
interbloqueos del consumidor. Nunca leer `.storage` desde plantillas para
obtener ajustes de una integración.

Publica también, por ID estable de zona, su actuador, sondas y habilitación.
Un consumidor debe verificar esas identidades y su propio permiso antes de
usar metas; no deducir correspondencias por el nombre ni convertir una fuente
no disponible en autorización. No publica helpers de autoridad, credenciales
ni contenido del journal; los diagnósticos descargables siguen redactados.


## Suelo externo y pausa de una sesión propia (opt-in)

`dry_floor_entity` puede enlazar sensor/number/input_number en °C o °F a un
suelo de arranque de 10–30 °C. Se interpreta como configuración persistente,
no telemetría ambiental. Si falta, tiene unidad inválida o queda fuera de rango,
no se inicia secado con un suelo alternativo. Sin binding se conservan los
suelos diurno/nocturno. El suelo seleccionado se congela antes de emitir: una
edición posterior no cambia el máximo, objetivo ni suelo de esa sesión.

`dry_pause_action` conserva `stop` por defecto. `retain_owned` solo mantiene
un ciclo con propiedad explícita previa durante la pausa; no inicia ni adopta
ciclos. Permanecen las salidas por máximo, suelo congelado, datos, permiso de
zona/secado, deshabilitación y seguridad eléctrica. Manual nunca se adopta.
Los registros de sesión y entidades conservan identidad al recargar.

### Concurrent admissions (opt-in)

See [unlimited drying](UNLIMITED_DRYING.md) for the separate admission-band and
service-budget switches. Overlapping permitted operation does not imply parallel
command transmission or per-head consumption: the plant executor remains serial
and aggregate energy retains its measured scope. Existing owners and their
frozen humidity endpoints are not renewed when another head joins.
