# Evidencia de la alfa

## Candidata0.2.0a4 · edición de humedad conjunta

Se conserva el núcleo154. El ensayo nativo de humedad/contabilidad añade una
pareja modificada atómicamente, rechazo fin≥inicio sin envenenar el siguiente
envío y lectura de configuración publicada sin permisos ni credenciales.
Una zona observadora sin medidor expone48objetos (12diagnóstico+36configuración).
Las cifras de las secciones siguientes son históricas, no el estado de esta candidata.

## Candidata0.2.0a3 · humedad y contabilidad

154pruebas del núcleo incluyen tablas HR por zona, capacidad independiente,
sesión congelada, máximo/bloqueo, autoridad/pausa/frescura, rango térmico,
compatibilidad calor+deshumidificador, espera de drenaje y distinción HR/rocío.
Contabilidad: fronteras de precio/día, coste negativo, tarifa/potencia ausentes,
reinicio sin interpolar, días DST23/25h, periodos naturales y ámbitos solapados.
`tests/ha_humidity_accounting.py` prueba además los gestores nativos, servicios
simulados de humedad→ACK→on, corte de sesión, Manual y almacenamiento propio.
Números:36por split (24térmicos+12HR),12por deshumidificador; una zona observadora
sin medidores expone47entidades (11diagnósticas+36configuración).
Los resultados de las suites y CI deben leerse por commit; no confundir este
contrato de pruebas con evidencia física de un modelo ni inspección visual.

## Candidata0.2.0a2 · ruido negativo acotado

134pruebas de núcleo y17verificaciones de ejecución HA temporal: la tolerancia
por medidor está desactivada por defecto, convierte unidades antes del límite,
rechaza negativos mayores y no alcanza energía/estadísticas ni protección del
suministro. Diagnóstico y planta reciben la misma lectura. Se conservan9checks
de números,11de formularios,14smoke y ciclo nativo; cero llamadas físicas.
CI valida ambas versiones HA y el artefacto/secretos del commit concreto.

## Candidata0.2.0a1 · objetivos como entidades

`tests/ha_number.py` usa el servicio real `number.set_value` en HA temporal:
24 entidades por split, categoría/unidades/área/etiquetas, perfil compartido,
rechazo atómico de objetivos incompatibles/no finitos, cambios rápidos sin
pérdida de celdas ni descarga de plataformas, herencia desde OptionsFlow,
autoridad de objetivos externos e identidad tras recarga. Prohíbe todos los
servicios físicos y verifica que la entrada continúa en observación.
La prueba incluye Manual normal sin falsa avería y recuperación incierta
todavía accionable. El ciclo de una zona observadora pasa de10 a34 entidades:
10 diagnósticas y24 de configuración. CI añade esta quinta suite a ambas
versiones HA; consultar la ejecución del commit, no presumirla por el workflow.

## Candidata · alta y configuración nativas

La candidata mantiene132pruebas de núcleo y añade `tests/ha_config_flow.py`:
prueba los gestores reales de alta/opciones de HA, no solo llamadas directas a
los métodos de los formularios. Verifica alta desde Añadir integración,
vinculación rápida, duplicados, nombre/área reales, edición de cuatro tablas,
eliminación efectiva de asignaciones opcionales, alta de otro split, recarga
con IDs estables y retirada conservando el dispositivo de su driver original.

Ensayo local enHA2026.11.0 temporal:11comprobaciones de flujo,14smoke,
16ejecución/energía y ciclo completo setup/reload/unload/remove. Servicios
físicos0, escrituras de configuración productiva0. CI ejecuta esas cuatro
suites enHA2026.10.4 y2026.11.0; consultar el resultado del commit concreto.
Ruff, compilación y revisión de secretos completan la validación técnica.

Los diálogos y dispositivos usan UI nativa; este ensayo no sustituye una
inspección visual ni una instalación HACS/Marketplace completa. No certifica
actuación, confort, consumo o relevo de un controlador de vivienda.

## Histórico de la primera alfa

05-11-2026; núcleo en Python3.14 y smoke con HA2026.10.4 en directorio temporal.

| Comprobación | Resultado observado |
|---|---|
| Pruebas de dominio | 31 correctas: tarifas/DST/precios incompletos, histéresis, compensación, Manual, potencia, deuda, sesiones y plantas independientes. |
| Ruff / compilación | Correctos. |
| Smoke HA | 10 verificaciones correctas; 0 llamadas físicas, 0 escrituras en configuración productiva. |
| Formularios | Alta, opción inválida→válida, objetivos por estancia, borrar binding opcional, reconstruir tramos atómicamente, impedir realimentación. |
| Runtime | Máquina de estados HA real aislada, 9 entidades diagnósticas construidas con IDs estables; lectura, redacción, persistencia y cierre. |
| Ciclo nativo HA2026.10.4 | Bootstrap vacío, alta real de entrada/plataformas, nueve entidades registradas, recarga con identidades iguales, unload y eliminación de su propia memoria: correcto. |
| GitHub CI | Batería para cada push/PR; consultar el resultado del commit publicado en Actions. |
| HACS/hassfest | Validadores oficiales sin checks ignorados; no certifican confort físico ni revisión oficial del producto. |
| Instalación por Marketplace/HACS y UI | Pendiente de ensayo visual en otra instalación. El ciclo nativo prueba el platform manager, no los diálogos del instalador ni funcionamiento físico. |
| Confort/ahorro/actuación | Actuación simulada en0.2; confort, consumo físico y traspaso por instalación no certificados. |

El dominio no importa Home Assistant ni consulta el reloj/red/actuadores. La
prueba usa fixtures ficticios; no incluye evidencia doméstica ni credenciales.
No confundir esta batería con las regresiones del controlador privado de una
vivienda, que pertenece a otro despliegue y otra autoridad.

## Ensayo de ejecución0.2

`python3 tests/ha_execution.py` carga solo HA temporal y servicios simulados.
Comprueba configuración portable, target→ACK→modo, Manual, corte, sensores
energéticos/contadores, formularios, reload y eliminación propia. No carga
dispositivos ni configuración de una vivienda. La CI lo ejecuta también con
la matriz de versiones HA; definir el workflow no demuestra que haya pasado
una ejecución remota nueva.

## Candidata · journal e interoperabilidad externa

Ensayo local05-11-2026: **113 pruebas de núcleo/protocolo**,12 verificaciones
smoke y15 de ejecución nativa en HA2026.11.0 temporal; setup/reload/unload/removal
con identidades conservadas. Diez entidades diagnósticas por zona en el perfil
observador de prueba;15 entidades en el ejemplo activo con medidor. Cuatro
servicios climate simulados, cero físicos y cero escrituras de configuración
productiva. Incluye publicación del journal antes del servicio, eco externo sin
escribir su ledger y cambio humano que reutiliza el mismo contexto.

La macro Jinja se incluye en el artefacto probado y se comprueban fase,
coincidencia, caducidad y prioridad humana. El requisito opcional de sonda interna
no permite que una zona inválida reserve la planta frente a zonas sanas.

Consultar Actions para los resultados del commit exacto y la matriz completa
de versiones. Ni esta tabla ni una PR en borrador certifican instalación por
el distribuidor, UI, hardware, plazos Manual particulares o traspaso de una casa.
