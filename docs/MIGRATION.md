# Migración y puertas de aceptación

La autorización de desarrollar no equivale a evidencia de confort/eficiencia.
Los plazos siguientes son **mínimos de observación útil**, no un temporizador que
active control automáticamente. Si no hay episodios comparables, la fase sigue
pendiente; no se hacen pruebas físicas para rellenar una cuota.

| Fase | Entrega | Puerta antes de avanzar |
|---|---|---|
| 0 Fiabilidad | Control existente sin veto por forecast, trabajo coalescido y propiedad de sesiones robusta | ≥72h sin pérdida de activaciones, trabajo atascado ni violación de Manual/protecciones. |
| 1 Regulación | Separar recuperación/mantenimiento y validar corrección/cadencia | ≥10 episodios utilizables por estancia activa; reducir ciclos de modo cortos sin empeorar error de confort ni energía comparable. |
| 2 Humedad | Validar suelo, duración, recuperación y coste térmico | ≥3 sesiones propias comparables: humedad absoluta/rocío, temperatura mínima, duración y rebote. Si dry no sirve, proponer otro equipo. |
| 3 Planificador | Shadow precio/umbrales por estancia | 7–14 días útiles; bloques completos, precio/datos faltantes, deuda, noches y multisplit sin contradicciones. |
| 4 Producto alfa | Núcleo y adaptador HA de observación configurable | Pruebas deterministas y smoke con versión HA objetivo; perfil privado separado. Esto es0.1, sin ejecutor. |
| 5 Un solo escritor | Ejecutor certificado y migración por instalación | Pruebas de Manual, restart, ACK tardío, apagado crítico, rollback, límite eléctrico y exclusión mutua. Sin convivencia de escritores. |
| 6 Beta HACS | Release pública, documentación y otra vivienda de prueba | Validadores HACS/hassfest, instalación/actualización/desinstalación, segunda instalación y revisión de privacidad. |

## Lo que no se debe adelantar

- No aplicar toda la tabla de humedad por precio de golpe; empezar con habitual y
  oportunista, verificar utilidad y ampliar después.
- No activar aprendizaje de ganancia con lecturas inválidas o ciclos mezclados
  de varias políticas. No trasladar una calibración entre estancias sin evidencia.
- No comparar euros entre días de distinta ocupación/meteorología como ahorro
  causal. Separar consumos medidos, estimaciones y simulaciones de decisiones.
- No instalar un segundo controlador sobre el mismo exterior para probarlo.

## Contrato del futuro ejecutor

Antes de habilitar actuación: intención identificada/persistida antes de enviar;
lectura fresca y autoridad por generación; reserva de instalación y presupuesto;
comando idempotente con ACK acotado; relectura; reconciliación de retrasos/restart;
parada crítica independiente; reanudación que nunca borre Manual o pausa. Los
límites de dry deben sobrevivir al selector off previo a un eco tardío.

Retirar todos los escritores anteriores de la instalación migrada, incluyendo
termostatos/scripts/automatizaciones indirectos. Inventariar consumidores y
conservar IDs o actualizar referencias explícitamente. Un virtual `climate`
normalizado es una propuesta de API futura, no una entidad de esta alfa.

## Reversión

1. Backup fechado/verificado de fuente exacta, registros y estados de autoridad.
2. Deshabilitar el nuevo escritor y reconciliar sesiones/deudas pendientes antes
   de devolver autoridad. No apagar equipos Manual como efecto de desinstalar.
3. Restaurar la fuente anterior mediante hash guard y recargar solo lo afectado.
4. Verificar configuración, definiciones cargadas, autoridades, consumidores y
   una observación natural. No llamar «rollback probado» a tener un backup.

Una casa debe seguir siendo manejable manualmente aunque el planificador falle.
