# Instalación y verificación

## Estado de distribución

Alfa local0.1.0a1. No hay URL pública o release descargable garantizada todavía.
Los enlaces GitHub del manifiesto son el destino de publicación previsto. La
estructura `custom_components/climate_orchestrator`, manifiesto, traducciones y
`hacs.json` prepara una integración, **no acredita validación HACS**.

HACS exige un repositorio público GitHub para distribuir una integración. Antes
de publicarlo: revisión de privacidad, licencia, URL real, hassfest, HACS action,
release y ensayo de instalación/actualización/eliminación en otro HA. También
falta el recurso de marca `brand/icon.png` requerido para publicar; esta alfa no
se declara HACS-ready. Véase la
[documentación de publicación de HACS](https://www.hacs.xyz/docs/publish/start/).

## Entorno de prueba

1. Preparar un HA desechable2026.10.x, configurado en Celsius, con estados de
   demostración. No habilitar otro escritor físico sobre equipos de una casa.
2. En desarrollo, copiar únicamente la carpeta de integración al directorio
   `custom_components` de ese entorno y reiniciar. Esto no es una instalación
   manual autorizada implícitamente para cualquier HA de producción.
3. Añadir integración desde la interfaz, tarifa, instalación y una estancia.
4. Comprobar diagnósticos, nombres traducidos, área/etiquetas, recarga y eliminación.
5. Ninguna automatización debe actuar a partir de propuestas alfa.

En una futura release pública, añadir el repositorio personalizado en HACS como
**Integration**, instalar y reiniciar; después añadir desde Dispositivos y servicios.
No basta con que HACS copie los archivos: hay que verificar también configuración
y entidades cargadas. La referencia de versiones HA ensayada no es una promesa
de compatibilidad futura.

## Pruebas del repositorio

La batería de dominio no requiere instalar HA:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components tests
```

Smoke con HA instalado en entorno aislado:

```sh
python3 tests/ha_smoke.py
```

Ejercita formularios, opciones, adaptador sobre la máquina de estados HA,
construcción de entidades, diagnóstico redactado y cierre. No acredita una
instalación completa mediante HACS ni funcionamiento físico. Una futura CI de
release debe ejecutar además los validadores oficiales
[hassfest](https://developers.home-assistant.io/docs/creating_integration_manifest/)
y [HACS](https://www.hacs.xyz/docs/publish/integration/).

No hay dependencias PyPI adicionales en ejecución. Ruff es exclusivamente una
herramienta de desarrollo. No guardar credenciales, backups de HA o Recorder en
este repositorio.
