# Cambios

## Candidata0.2.0a6 · desarrollo aislado, sin release

- Suelo de secado externo opcional como configuración persistente; validación,
  conversión absoluta de temperatura y congelación al reservar la sesión.
  Perder la fuente bloquea nuevos ciclos sin inventar un respaldo.
- Pausa de ciclos propios configurable: detener (predeterminado) o conservar
  solo una sesión ya reservada, manteniendo máximo, suelo, datos y autoridad.

- Salida térmica off-only opt-in al retirar el permiso del modo ya activo.
  Predeterminado hold, sin adoptar Manual/dry ni convertir pausa en apagado;
  revalidación tras persistir cancela intenciones ante recuperación o Manual nuevo.
- Un veto ordinario de modo no oculta la protección por exceso ya observado.
- Permiso opcional de ocupación térmica local para retornos: no falsea presencia
  de la casa ni autoriza secado/gestión de carga conjunta con la vivienda vacía.
- Opciones avanzadas nativas, validación y traducciones; sin activar control
  por actualización ni modificar perfiles o entidades instaladas.

## Candidata0.2.0a4 · sin release

- Editor nativo de humedad por rango con inicio/fin juntos, guardado atómico,
  retorno explícito a herencia y errores específicos. No obliga a crear una
  pareja intermedia inválida para cambiar ambos umbrales.
- Diagnóstico de configuración validada (política y tiempos de instalaciones)
  para dashboards y consumidores explícitos. Es de solo lectura; no publica
  credenciales, registros de órdenes ni concede autoridad física.
- Mensajes de objetivos inválidos distinguen también la histéresis de humedad.

## Candidata0.2.0a3 · sin release

- Tablas y entidades nativas de HR para iniciar/terminar secado por estancia y
  precio, con histéresis validada y endpoint de sesión congelado.
- Alta nativa de deshumidificador independiente, planta propia, permisos y
  pausa explícita, límites de temperatura/tiempo, ACK de humedad antes de on,
  Manual y bloqueo del episodio tras máximo/apagado externo.
- Punto de rocío ambiental fresco y servicio húmedo pendiente visible incluso
  con calefacción activa; no considerar calor como extracción de agua.
- Reposo/drenaje configurable antes de volver de frío/dry a calor, sin rebajar
  otras esperas, sin prometer batería seca y sin purga fan_only automática.
- kWh/EUR hoy/ayer/semana/mes/año por medidor y subtotal sin ámbitos solapados.
  Potencia medida con frescura, precios por intervalo, DST, cobertura, huecos
  de reinicio e histórico desconocido explícitos; fuentes/Recorder intactos.
- Contenedores QA desechables, sin red/montajes/credenciales de producción;
  pruebas del núcleo, servicios/formularios nativos y persistencia.

## Candidata0.2.0a2 · sin release

- Tolerancia opcional por medidor de consumo para pequeños negativos de
  reposo: predeterminado0W, configurable0–20W. Unidades W/kW normalizadas antes
  del umbral; valores más negativos siguen inválidos. No cambia fuente,
  contadores, estadísticas ni protección de suministro.
- Diagnóstico y coordinación de carga usan la misma lectura validada del
  medidor; el ajuste está disponible en el formulario nativo de consumo.

## Candidata0.2.0a1 · sin release

- Objetivos ambientales por split/precio/fase como entidades `number` nativas
  de Configuración, con nombres de rango, unidad, área, etiquetas e identidad
  estable; el mismo perfil de las opciones, no consignas directas del equipo.
- Validación atómica e indicación de herencia/fuente externa; cambios rápidos
  de tablas sin descargar controles ni perder celdas. Revocan propuestas
  antiguas y conservan Manual, fuentes, autoridad y memoria.
- La elección normal de Manual no se representa como fallo de ejecución;
  incertidumbre y errores reales siguen visibles.
- Ensayo del servicio real de números y formularios en HA temporal, sin
  llamadas físicas; observadores no adquieren autoridad al actualizar.

## Candidata0.2 · sin release

- Alta nativa simplificada desde Dispositivos y servicios; split y sonda
  externa con humedad opcional, metadatos reales y comprobación de duplicados.
- Opciones agrupadas y menú por split para equipos/sondas, las cuatro tablas
  de temperatura y permisos/compensación; dispositivos lógicos con enlace de
  configuración, sin apropiarse del dispositivo del fabricante.
- Los campos opcionales usan sugerencias nativas para permitir eliminar una
  asignación sin que el formulario vuelva a insertar la anterior.
- Prueba de gestores nativos de configuración y opciones, incluido alta,
  recarga con identidad estable y retirada sin eliminar el equipo físico.

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
