# Cambios

## 0.2.0a16 · estado térmico de la casa para gráficas

- `house_thermal_demand` (apagado / calor·mantenimiento / calor·demanda /
  frío·mantenimiento / frío·demanda / mixto) y `house_demand_level` (0/1/2):
  un único estado graficable que separa una unidad que trabaja para alcanzar el
  objetivo de otra encendida con la sala ya en objetivo. Atributos con el
  estado de cada estancia y el número de estancias en demanda/mantenimiento.

## 0.2.0a15 · demanda térmica por estado real

- `thermal_demand`/`demand_level` describen la necesidad de la sala y el
  estado de la unidad aunque el plan esté en espera o bloqueado: una unidad en
  marcha con la sala por debajo de su objetivo es *demanda*; con la sala en
  objetivo es *mantenimiento*. «Secando» solo si la unidad está en dry.

## 0.2.0a14 · auditoría de coherencia y demanda térmica

Correcciones:

- Un comando sin confirmar (`uncertain`) ya no veta para siempre la cabeza:
  solo bloquea durante su ventana en vuelo, y **Reanudar** cierra la
  transacción abierta conservando los ecos tardíos. Antes, tras un timeout
  la zona rechazaba toda orden aunque se reanudara.
- Una sesión de secado propia ya no queda atascada en `dry_ack_pending` si la
  unidad aparece en calor/frío/ventilador tras la ventana de confirmación: el
  motor la da por terminada y el control térmico y las protecciones vuelven.
  La reserva persistida se libera en la comprobación de seguridad.
- Una zona con «permitir durante el sueño» desactivado se detiene (una vez) al
  entrar el periodo de sueño si estaba en calor/frío, en lugar de seguir
  encendida sin control. Pausa global, Manual y permisos externos no cambian.
- El periodo de sueño pertenece a su tarde: con inicio de noche pasada la
  medianoche ya no se acorta ni alarga al cambiar de día laborable a fin de
  semana. Horarios habituales sin cambios.
- Restauración robusta: contenedores `zones`/`plants`/`bindings`/`accounting`
  o archivo de contabilidad con tipo incorrecto se conservan para recuperación
  con error explícito; filas de contabilidad malformadas se archivan.
- Editar una planta sin tiempos guardados usa los valores del modelo (20/20/60/
  120/5 min), no cero; una edición inválida ya no deja el candidato en el flujo.
- `async_migrate_entry` usa `CONFIG_VERSION`.

Novedad:

- Sensores `thermal_demand` (apagado / mantenimiento sin demanda / demanda /
  parando / sin gestión / secando) y `demand_level` (0/1/2) por habitación
  térmica, con el déficit de temperatura. Distinguen una unidad que trabaja
  para alcanzar el objetivo de otra encendida con la sala ya en objetivo y
  consigna relajada para evitar ciclos. Es lectura de estado/plan, no medida de
  compresor.

Documentación: README/INSTALACIÓN y CHANGELOG alineados con la versión.

## 0.2.0a10 · coherencia de versión instalada y diagnóstico

- Corrige la versión anunciada en el diagnóstico nativo: ahora coincide con el
  manifiesto. La versión a9 conservaba la constante de a8.
- Pruebas de coherencia entre manifiesto/constante y del sensor de configuración
  cargado por HA; sin cambios de política, perfil, autoridad o metas.

## 0.2.0a9 · configuración nativa y recuperación segura

- Los 49 ajustes de política se organizan en seis formularios: calor/frío,
  secado, humedad, potencia, frescura/cadencia y precios. Se conserva un
  formulario completo avanzado. Cada grupo guarda solo su delta.
- Errores relacionales junto a los campos: histéresis, sobrepaso, duración,
  carga compartida y margen de precio. Un error no guarda cambios parciales.
- Editor por fuente para recepción, origen o contrato del proveedor, con
  ruta de fecha tipada, borrado real y retorno individual al predeterminado.
  Se conserva el objeto avanzado con el mismo consumidor runtime.
- Incluye correcciones locales posteriores a a8: validación anidada del
  journal antes de cargar/guardar y límites comunes de modelo/formulario.
- Revisión ordinaria coalescida a 300 s con guardas de 60 s, eventos urgentes
  y plazos independientes; sin retrasar cortes o Manual hasta esa cadencia.
- Secado sin máximo explícito con cero, concurrencia/presupuesto opt-in y
  reservas térmicas/rocío persistentes. No se activan al actualizar perfiles.
- Actualizar o editar opciones no concede autoridad, borra Manual ni certifica
  paridad/relevo de un controlador existente. Sin cambios YAML de instalación.

## 0.2.0a8 · suelo térmico común opt-in

- Admisión y continuidad pueden compartir max(suelo configurado, objetivo de calor vigente + `dry_heat_offset`), sin margen adicional de arranque. Valor no configurado conserva comportamiento previo.
- Objetivos editables, IDs, autoridad, propiedad y plazos preservados al actualizar.
- Incluye estrategias/actividad opcionales de la candidata anterior, sin activar ejecución al actualizar.
- No declara paridad con controladores externos ni retira caps/presupuestos nativos: el controlador externo sigue siendo el único escritor hasta completar su migración.


## Candidata0.2.0a7 · estrategias y actividad opcional, sin release

- Tres estrategias con preferencias, flexibilidad y esperas explícitas sobre el
  mismo motor; compatibilidad `legacy` por defecto para entradas anteriores.
- Selector nativo traducido, aplicación opt-in adicional e inmediata sin reload
  ni pérdida de Manual, presupuestos o plazos. Preview separado de metas activas.
- Varias fuentes opcionales de presencia/movimiento/actividad por habitación;
  estados configurables, evidencia triestado y captura de pulsos entre recálculos.
- Relojes de origen/recepción diferenciados y aviso Repairs agrupado/recuperable;
  temperaturas estables y cachés no se confunden con medidas nuevas probadas.
- Monedas y unidades explícitas en tarifa/costes. Se rechazan mezcla, ambigüedad
  y relabel de ledger; energía medida y contadores originales permanecen intactos.
- Persistencia nueva separada de presupuestos existentes, pruebas de servicios y
  gestores de flujo HA aislados, y contrato de producto con límites explícitos.
- Sin instalación productiva, publicación, pruebas físicas ni ahorro demostrado.

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
