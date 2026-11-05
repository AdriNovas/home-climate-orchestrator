# Cambios

## Candidata0.2 · sin release

- Modulación continua opcional de consigna, respuesta ambiental acotada y
  reportes distintos, sin caducidad rutinaria del mantenimiento.
- Consumo compartido observado por medidor de planta, referencias agregadas
  por número de cabezas y retirada escalonada con presupuesto persistente.
- Tablas por split de calor/frío y día/sueño por tramo, herencia y validación
  atómica, con opciones nativas en español/inglés.
- Las entradas observadoras y releases existentes no adquieren autoridad ni
  activan estas políticas como efecto de una actualización.

## 0.1.0a1 · 2026-11-05 · alfa pública de observación

- Núcleo determinista y configuración versionada de casa/instalación/estancia.
- Tarifas PVPC/plana/tramos/intervalos, negativos y DST.
- Demanda térmica, mantenimiento, arbitraje, suelo y deuda de humedad configurables.
- Adaptador HA **solo observación**, opciones nativas, entidades y diagnóstico.
- Traducciones inglés/español y pruebas sintéticas/HA temporal.
- Repositorio personalizado HACS/Marketplace, marca propia y CI de validación
  y secretos; no incluida en el catálogo.
- Sin ejecutor físico, calibración automática ni ahorro certificado.
# Candidata 0.2.0a0 · sin release

- Propuestas opcionales de mantenimiento con consigna relajada y espera acotada.
- Corte económico opcional con precio conocido, histéresis y estabilidad de
  lecturas distintas; preserva confort, mínimos, Manual y arbitraje multisplit.
- Permiso automático global configurable; pausa ante off o dato desconocido.
- Ejecutor opt-in separado: journal, confirmación por estado, generaciones,
  rechazo de intención revocada, Manual local y reconciliación conservadora.
- Corte crítico independiente, sesiones dry propias con plazo persistente y
  bloqueo de duplicados entre entradas activas.
- Medidores editables por vivienda/planta/estancia: W/kW, Wh/kWh/MWh y EUR/h;
  sin repartir agregados, duplicar fuentes ni modificar estadísticas originales.
- Permisos, objetivos y desfases externos; selectores de autoridad con estados
  configurables y conversión °C/°F de sensores/actuadores.
- Pruebas de protocolo y ciclo nativo con servicios simulados. No certifica
  traspaso de una vivienda ni activación física; observación sigue por defecto.
- Publicación de expectativas persistidas antes del servicio, journal v1 nativo
  y contrato Jinja para detectores Manual externos. Los registros externos se
  leen, no se escriben ni renuevan. Contexto humano explícito prevalece.
- Barrera crítica externa JSON con certificado de generación releído al emitir;
  publicación diagnóstica fallida no bloquea la vía independiente off-only.
- Entrada opcional de respuesta medida acotada y requisito por equipo de feedback
  interno fresco; una zona sin feedback no reserva la planta contra zonas sanas.
