> Esta rama es la candidata 0.2.0a16. La instalación
> pública0.1 sigue en observación. No cambiar la autoridad de una vivienda por
> el solo hecho de actualizar archivos.

# Instalar con Marketplace o HACS

Repositorio: [AdriNovas/home-climate-orchestrator](https://github.com/AdriNovas/home-climate-orchestrator).
Dominio HA: `climate_orchestrator`. Versión inicial: **0.1.0a1, prerelease**.
Requiere HA2026.10.4 o superior; Marketplace está disponible desde2026.11.

**Alfa de observación:** instalar añade propuestas/diagnósticos. No envía órdenes
al AC, no reemplaza el control existente ni cambia automáticamente su configuración.
No está incluida en el catálogo: añadirla por URL. No implica revisión/aprobación
del proyecto Home Assistant.

## Marketplace · HA2026.11+

1. Abrir **Ajustes → Marketplace → Añadir desde enlace**.
2. Introducir `https://github.com/AdriNovas/home-climate-orchestrator`.
3. Si pide tipo, seleccionar **Integración**. Conectar GitHub si la interfaz lo requiere.
4. Habilitar versiones preliminares para este repositorio y seleccionar la versión preliminar más reciente (0.2.0a16).
   Marketplace ofrece estables por defecto; el interruptor de prereleases puede
   necesitar habilitarse en el dispositivo Marketplace del repositorio.
5. Instalar y seguir cualquier aviso de reinicio; después añadir la integración
   desde **Ajustes → Dispositivos y servicios** si no abre el asistente.

Referencia: [Marketplace y repositorios personalizados](https://www.home-assistant.io/integrations/marketplace/#custom-repositories).

## HACS · instalaciones anteriores

1. Abrir HACS → menú de repositorios personalizados.
2. Añadir la misma URL como **Integration**.
3. Seleccionar la prerelease más reciente (0.2.0a16), habilitando versiones beta si no aparece.
4. Descargar, reiniciar cuando lo solicite HA y añadir **Home Climate Orchestrator**
   en Dispositivos y servicios.

[Abrir repositorio en HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=AdriNovas&repository=home-climate-orchestrator&category=integration).
El paquete es el mismo para ambos; no instalar dos copias del dominio.

## Vincular tu instalación

1. Integrar previamente cada split y sensor externo en HA.
2. Abrir **Ajustes → Dispositivos y servicios → Añadir integración → Home Climate
   Orchestrator** y elegir nombre, zona horaria y tarifa.
3. Crear una unidad exterior y declarar si los splits comparten sentido.
4. Vincular cada split: entidad del AC, temperatura externa, humedad opcional,
   instalación y área/etiquetas. Nombre opcional tomado del equipo seleccionado.
5. Finalizar en observación. En la ficha de integración pulsar **Configurar**:
   splits, unidades exteriores, confort/horarios, consumo y fuentes/funcionamiento.
6. Para un split, seleccionar **Configurar un split o estancia** y elegir
   equipo/sondas, temperaturas por precio o permisos/compensación avanzados.
7. En el dispositivo lógico de cada split, **Configuración** ofrece también
   los objetivos como números editables: calor/frío y día/sueño por rango de
   precio. Son las mismas tablas, no helpers ni consignas del AC duplicadas.

Este recorrido simplificado corresponde a la candidata0.2. La release pública
0.1 también se añade desde Dispositivos y servicios, pero no incorpora aún esta
organización nueva. HACS instala el código; el asistente nativo configura los
equipos. El catálogo HACS y la publicación de una release son pasos distintos.

Ver [compatibilidad](COMPATIBILITY.md) y [configuración](CONFIGURATION.md).
Los JSON de `examples/` son ficticios y documentan el esquema: no hay importador
JSON en la UI. No conectar propuestas alfa a automatizaciones de actuación.

## Actualizar y eliminar

Antes de actualizar, guardar configuración/backup. Marketplace/HACS sustituye
la carpeta de código; el estado del usuario está en el almacenamiento HA, no allí.
Las actualizaciones de código cargado requieren reiniciar según indique HA.

Para retirar: eliminar primero la entrada de integración en Dispositivos y
servicios y después desinstalar el repositorio. La alfa no apaga ni reconfigura
los equipos al retirarla. Seguir cualquier reparación/aviso de reinicio.

## Verificación y desarrollo

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components tests
# En un entorno desechable con Home Assistant instalado:
python3 tests/ha_smoke.py
python3 tests/ha_lifecycle.py
python3 tests/ha_config_flow.py
```

CI ejecuta el núcleo, Gitleaks sobre el historial, smoke HA y los validadores
oficiales HACS/hassfest. El smoke no es un ensayo físico ni una inspección de UI.
Consultar [validación](VALIDATION.md) y los resultados del commit en Actions.
La instalación completa por ambas interfaces sigue siendo un ensayo distinto.

Sin dependencias PyPI adicionales en ejecución. No copiar configuración de otra
casa ni instalar carpetas privadas junto al código.
