# Contribución y privacidad

- Solo perfiles ficticios y fixtures sintéticos en Git. Nunca tokens, endpoints
  domésticos, ID de persona/teléfono, Recorder, direcciones o diagnósticos locales.
- El núcleo no importa HA ni consulta reloj, red o disco. Tiempo explícito.
- Cambios de decisiones deben probar límites/fallos, no solo el camino feliz.
- Antes de commit: pruebas, Ruff, compilación y revisión del diff/archivos nuevos.
- Antes de release: puertas de `docs/MIGRATION.md`, validadores oficiales, URLs
  reales y smoke de instalación. CI no tiene secretos ni despliega viviendas.
- Las incidencias deben redactarse. El diagnóstico descargable está reducido;
  no adjuntar todos los atributos de las entidades sin revisarlos.

Licencia MIT. No introducir compatibilidad ficticia con equipos no ensayados.
