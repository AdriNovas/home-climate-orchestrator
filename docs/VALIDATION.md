# Evidencia de la alfa

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
