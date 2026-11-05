# Home Climate Orchestrator

![Home Climate Orchestrator](custom_components/climate_orchestrator/brand/icon.png)

Planificador doméstico de temperatura y humedad según tarifa eléctrica, con
sensores ambientales externos y splits de aire acondicionado agrupados por instalación.

**0.1.0a1 · alfa pública, solo observación.** Genera propuestas y diagnósticos;
**no envía órdenes**, no sustituye al termostato y no promete ahorro. El
repositorio se distribuye como integración personalizada para HACS y el
Marketplace de Home Assistant; **no está incluido en su catálogo oficial**.

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

- Asistente nativo de Home Assistant y opciones en español/inglés.
- Tarifas PVPC nativo, precio fijo, tramos semanales con excepciones por fecha o
  proveedor genérico de intervalos. Precios negativos y cambios de hora reales.
- Objetivos de calor, frío y humedad por banda de precio. Horarios laborables y
  fin de semana; excepciones térmicas diurnas por estancia.
- Propuestas de recuperación y mantenimiento: histéresis, corrección acotada de
  consigna, cadencia y límites temporales por instalación.
- Secado con temperatura prioritaria, suelo térmico independiente de la tarifa,
  presupuesto diario, espera entre intentos y deuda de humedad persistente.
- Reservas de sentido para equipos que comparten exterior y arbitraje de potencia.
- Entidades nativas con identificadores estables, áreas reales, etiquetas,
  categoría de diagnóstico y motivos legibles. Diagnóstico descargable redactado.

El núcleo no depende de Home Assistant: recibe observaciones y hora explícitas.
El adaptador HA observa capacidades `climate`, sin asumir compresor, consumo por
estancia ni equivalencia entre temperatura interna y sensor ambiental.

## Límites importantes

La alfa admite propuestas para `heat`, `cool` y `dry` en equipos `climate` con
límites explícitos y HA configurado en Celsius. Sensores externos Fahrenheit se
convierten; equipos nativos Fahrenheit todavía no se certifican. Radiadores,
calderas, suelo radiante, ventilación, deshumidificadores dedicados y bombas de
calor por agua requieren adaptadores y ensayos propios: **no son compatibles por
el mero hecho de aparecer como entidad**.

No hay ejecutor físico, aprendizaje térmico automático, cálculo de COP, modelo
predictivo de la vivienda ni optimización global del consumo. El planificador
tarifario de esta versión compara bloques completos de secado; los objetivos
térmicos siguen la banda actual. No simula una temperatura futura alcanzada.

## Empezar

1. Leer [instalación y pruebas](docs/INSTALLATION.md). La instalación alfa es en
   un entorno de prueba, no una instrucción para reemplazar un control doméstico.
2. Configurar tarifa, instalaciones y estancias desde **Dispositivos y servicios
   → Añadir integración → Climate Orchestrator**.
3. Consultar [configuración](docs/CONFIGURATION.md), especialmente sensores,
   Manual, unidades, tramos y significados de los umbrales de humedad.
4. Revisar propuestas sin conectarlas a automatizaciones de actuación.
5. Para una futura migración, cumplir [puertas de aceptación y reversión](docs/MIGRATION.md).

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
```

`ha_smoke.py` usa un directorio temporal y un Home Assistant aislado; no carga
integraciones domésticas ni llama servicios de actuación. La validación física,
visual y de una instalación HACS real son comprobaciones distintas y pendientes.

### English summary

Observation-only Home Assistant alpha for tariff-aware temperature and humidity
planning. Configurable PVPC/fixed/flat/interval tariffs, zones and shared plants.
No actuator commands, no measured savings, no universal HVAC compatibility claim.
Installable as a custom repository, not included in the HACS/Marketplace catalog.
Keep real home profiles and histories outside this repo.
