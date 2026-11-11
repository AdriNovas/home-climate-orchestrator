# Home Climate Orchestrator

![Home Climate Orchestrator](custom_components/climate_orchestrator/brand/icon.png)

Planificador doméstico de temperatura y humedad según tarifa eléctrica, con
sensores ambientales externos y splits de aire acondicionado agrupados por instalación.

**0.2.0a8 · alfa; actualización sin traspaso automático de control.** Añade ejecución
opcional con registro/confirmación y medidores energéticos configurables. Toda
entrada comienza en observación; actualizar no activa órdenes. La versión pública
0.1.0a1 continúa siendo observadora. Sin promesa de ahorro ni compatibilidad universal.

Se distribuye como repositorio personalizado HACS/Marketplace; no está en su catálogo.
Ver [ejecución, energía y asignaciones portables](docs/EXECUTION_ENERGY.md).
Ver [humedad, deshumidificadores y contadores por periodo](docs/HUMIDITY_ACCOUNTING.md).
Ver [Precio/Equilibrado/Confort y actividad opcional por habitación](docs/STRATEGIES_ACTIVITY.md).

[Instalar con HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=AdriNovas&repository=home-climate-orchestrator&category=integration)
· [Instalación Marketplace/HACS](docs/INSTALLATION.md)
· [Iniciar configuración tras instalar](https://my.home-assistant.io/redirect/config_flow_start/?domain=climate_orchestrator)

## Para otra casa o marca de AC

No hay nombres de dispositivos, habitaciones ni tarifas de una vivienda incrustados.
Por estancia se vincula una entidad `climate` de la integración del fabricante,
un sensor externo de temperatura y, opcionalmente, otro de humedad. Pueden ser
Zigbee, Bluetooth, Wi-Fi o MQTT: importa su estado/unidad en HA, no la marca.
Se declara qué splits comparten unidad exterior para evitar propuestas de modos
incompatibles. La tarifa se elige por separado: PVPC, plana o tramos configurables.

El AC debe estar integrado primero en HA. Un emisor infrarrojo sin estado fiable
no se considera equivalente a un equipo con modos y límites confirmados.
Ver [compatibilidad y vinculación](docs/COMPATIBILITY.md).

## Qué hace esta versión

- Alta desde **Dispositivos y servicios → Añadir integración**, sin YAML.
  Vinculación rápida de splits/sondas y opciones agrupadas en español/inglés.
- Tarifas PVPC nativo, precio fijo, tramos semanales con excepciones por fecha o
  proveedor genérico de intervalos. Precios negativos y cambios de hora reales.
- Objetivos de calor, frío y humedad por banda de precio. Horarios laborables y
  fin de semana; excepciones térmicas diurnas por estancia.
- Objetivos ambientales editables como entidades `number` de configuración,
  por split, tramo y día/sueño, sincronizadas con los formularios nativos.
- Inicio/fin de humedad por estancia y precio; deshumidificadores independientes
  nativos con sondas externas, sesión acotada y pausas/Manual preservados.
- Energía y coste variable medidos hoy, ayer, semana, mes y año, con cobertura
  explícita, persistencia y sin duplicar medidores ni inventar datos anteriores.
- Propuestas de recuperación y mantenimiento: histéresis, corrección acotada de
  consigna, cadencia y límites temporales por instalación.
- Secado con temperatura prioritaria, suelo térmico independiente de la tarifa,
  presupuesto diario, espera entre intentos y deuda de humedad persistente.
- Reservas de sentido para equipos que comparten exterior y arbitraje de potencia.
- Potencia/energía por vivienda, instalación o estancia, sin duplicar contadores.
- Objetivos, desfases y permisos externos asignables, sin dependencias de una casa.
- Ejecución opt-in con ACK, generaciones, Manual local y corte crítico independiente.
- Journal nativo de solo lectura y compatibilidad con detectores externos,
  sin sobrescribir sus registros ni conceder autoridad por reconocer un eco.
- Entidades nativas con identificadores estables, áreas reales, etiquetas,
  categoría de diagnóstico y motivos legibles. Diagnóstico descargable redactado.

El núcleo no depende de Home Assistant: recibe observaciones y hora explícitas.
El adaptador HA observa capacidades `climate`, sin asumir compresor, consumo por
estancia ni equivalencia entre temperatura interna y sensor ambiental.

## Límites importantes

La alfa admite propuestas para `heat`, `cool` y `dry` en equipos `climate` con
límites explícitos. El adaptador convierte °C/°F en sensores y consignas; los
ensayos sintéticos no certifican un modelo físico concreto. Radiadores,
calderas, suelo radiante, ventilación y bombas de
calor por agua requieren adaptadores y ensayos propios: **no son compatibles por
el mero hecho de aparecer como entidad**.

El ejecutor opcional está separado del núcleo; no hay aprendizaje térmico
automático, cálculo de COP, modelo predictivo ni optimización global del consumo. El planificador
tarifario de esta versión compara bloques completos de secado; los objetivos
térmicos siguen la banda actual. No simula una temperatura futura alcanzada.

## Empezar

1. Leer [instalación y pruebas](docs/INSTALLATION.md). La instalación alfa es en
   un entorno de prueba, no una instrucción para reemplazar un control doméstico.
2. Abrir **Dispositivos y servicios → Añadir integración → Home Climate
   Orchestrator**. Elegir tarifa, unidad exterior, split y sonda ambiental.
3. Consultar [configuración](docs/CONFIGURATION.md), especialmente sensores,
   Manual, unidades, tramos y significados de los umbrales de humedad.
4. En **Configurar**, administrar **Splits y estancias**, **Unidades exteriores**,
   **Confort y horarios**, **Consumo y medidores** y **Fuentes y funcionamiento**.
   Cada split tiene su menú de equipo/sondas, cuatro tablas de temperaturas y
   permisos/compensación. Revisar propuestas en observación.
5. Antes de habilitar control, cumplir [puertas de aceptación y reversión](docs/MIGRATION.md).

Documentación técnica: [arquitectura](docs/ARCHITECTURE.md),
[decisiones de diseño](docs/DECISIONS.md), [privacidad y contribución](CONTRIBUTING.md),
[versiones](CHANGELOG.md). Los ejemplos de `examples/` son ficticios.

## Pruebas locales

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components tests
# Solo en un entorno desechable con HA 2026.10 instalado:
python3 tests/ha_smoke.py
python3 tests/ha_lifecycle.py
python3 tests/ha_config_flow.py
python3 tests/ha_execution.py
```

`ha_smoke.py` usa un directorio temporal y un Home Assistant aislado; no carga
integraciones domésticas ni llama servicios de actuación. La validación física,
visual y de una instalación HACS real son comprobaciones distintas y pendientes.

### English summary

Development candidate for tariff-aware climate planning, optional journaled
execution, and explicitly scoped power/energy sources. Configurable PVPC/fixed/flat/interval tariffs, zones and shared plants.
Observation remains the default; no automatic takeover on upgrade. No measured
savings or universal HVAC compatibility claim.
Installable as a custom repository, not included in the HACS/Marketplace catalog.
Keep real home profiles and histories outside this repo.
