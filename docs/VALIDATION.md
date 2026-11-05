# Evidencia de la alfa local

05-11-2026; núcleo en Python3.14 y smoke con HA2026.10.4 en directorio temporal.

| Comprobación | Resultado observado |
|---|---|
| Pruebas de dominio | 31 correctas: tarifas/DST/precios incompletos, histéresis, compensación, Manual, potencia, deuda, sesiones y plantas independientes. |
| Ruff / compilación | Correctos. |
| Smoke HA | 10 verificaciones correctas; 0 llamadas físicas, 0 escrituras en configuración productiva. |
| Formularios | Alta, opción inválida→válida, objetivos por estancia, borrar binding opcional, reconstruir tramos atómicamente, impedir realimentación. |
| Runtime | Máquina de estados HA real aislada, 9 entidades diagnósticas construidas con IDs estables; lectura, redacción, persistencia y cierre. |
| GitHub CI | Definido, no ejecutado remotamente: repositorio todavía local. |
| HACS/hassfest | Pendientes de release y repositorio público real; no certificados. |
| Instalación/actualización/eliminación UI completa | Pendiente en HA de prueba independiente. El smoke no cubre el platform manager completo. |
| Confort/ahorro/actuación | No probados por esta alfa; no contiene ejecutor. |

El dominio no importa Home Assistant ni consulta el reloj/red/actuadores. La
prueba usa fixtures ficticios; no incluye evidencia doméstica ni credenciales.
No confundir esta batería con las regresiones del controlador privado de una
vivienda, que pertenece a otro despliegue y otra autoridad.
