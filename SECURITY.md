# Seguridad y privacidad

El repositorio solo debe contener código, documentación y fixtures ficticios.
No adjuntar tokens, `.storage`, base de datos de HA, diagnósticos sin revisar,
IDs de dispositivos/personas, ubicaciones, presencia o endpoints domésticos.

Si encuentras una vulnerabilidad, usa la pestaña **Security → Report a vulnerability**
del repositorio, cuando esté habilitada. No abras un issue público con credenciales
o datos de una vivienda. Si no está disponible, abre un issue sin detalles
sensibles para acordar un canal privado antes de compartirlos.

La alfa0.1 es observadora y no llama servicios de actuadores. Eso no elimina los
riesgos de cualquier código Python instalado en HA: instalar solo versiones
revisadas y mantener backups. Los atributos locales pueden incluir lecturas;
el diagnóstico descargable intencionadamente no incluye bindings ni lecturas.

La CI revisa todo el historial con Gitleaks. Antes de publicar se revisan también
árbol, metadatos Git y archivos excluidos: un escáner sin hallazgos no sustituye la
revisión del contenido. No hay credenciales domésticas necesarias en GitHub Actions.
