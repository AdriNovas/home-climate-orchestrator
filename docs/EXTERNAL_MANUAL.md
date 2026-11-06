# Interoperabilidad con un gestor Manual existente

La candidata0.2 incorpora un **contrato de procedencia**, no un importador de
políticas domésticas. Configurar estas fuentes no certifica horarios, excepciones
Manual, protecciones o un cambio de controlador. Requiere pruebas de la
instalación y un único árbitro ordinario de los actuadores.

## Journal nativo de solo lectura

Cada estancia tiene un sensor diagnóstico **Registro de ejecución**, también en
observación para poder preparar sus consumidores. Su `unique_id` es
`<entry_id>_<zone_id>_execution_journal`; resolver el `entity_id` en el registro,
no adivinarlo por el nombre de la estancia. Actualizar/recargar conserva identidad.

Sus atributos v1 son:

- `schema_version: 1`, `actuator`, `execution_mode`, `temperature_unit: °C`.
- `phase`: `idle`, `prepared`, `sending`, `acked`, `cancelled` o `uncertain`.
- `command_id`, `generation`, `expected` y `critical_cut_active`.
- Cada expectativa tiene `mode`, `target` y `until` absoluto UTC en segundos.

El ejecutor guarda primero en su almacenamiento y publica **esa copia persistida**
antes de llamar al servicio. Una publicación fallida bloquea emisiones ordinarias,
pero no impide los apagados de la vía crítica independiente. No es protección
autónoma durante una caída de HA, ni prueba de compresor o efecto físico.

Un detector externo puede reconocer un eco únicamente si:

1. El sensor pertenece al actuador configurado y está disponible.
2. El esquema es v1, está en `control` y la fase es `sending`, `acked` o `uncertain`.
3. Coinciden modo y consigna con una expectativa aún vigente, con lease acotada.
4. No hay contexto humano explícito. Un evento humano no se consume como ACK,
   aunque alcance la misma consigna. Sin procedencia humana identificable existe
   ambigüedad: no se ofrece detección humana perfecta.

La función pura `domain.provenance.journal_echo` y la macro distribuida
`templates/execution_echo.jinja` implementan este contrato. La macro recibe el
mapping de atributos, actuador, modo, consigna en°C, hora epoch y `user_id`.
Puede incorporarse al construir la plantilla del consumidor; no exige instalar
otro componente ni un archivo global de `custom_templates`.

Reconocer un eco nativo **no escribe el ledger antiguo**, no prolonga su lease,
no cambia plazos Manual y no autoriza otro arranque. Los ecos antiguos del corte
se conservan solo por sus plazos originales; una orden transmitida no se cancela
retroactivamente. El detector sigue atendiendo los cambios ajenos al journal.

## Lectura de emisores externos retenidos

Campos opcionales de estancia:

| Campo | Contrato |
|---|---|
| `expected_ledger_entity` | JSON compacto v1 con `q`, máximo3 filas `[from_mode, from_target, to_mode, to_target, until, ack]`. |
| `critical_ledger_entity` | Registro crítico con `at`, `until`, `late` y finales invalidados `old`; exige la barrera externa correspondiente. |
| `response_entity` | Respuesta medida compacta `{at, m, g, b}`: timestamp, modo, objetivo°C y esfuerzo adicional°C. |
| `require_internal_feedback` | Si está activo, no se envían correcciones/arranques térmicos sin sonda interna fresca. No convierte un aparato sin esa capacidad en compatible. |

Los códigos de modo compacto son `off, heat, cool, dry, fan_only, auto`, en ese
orden desde0. Solo se reconocen transiciones exactas/parciales de registros
pendientes y finales exactos de los confirmados, con lease restante≤60s. Un modo
desconocido, estructura inválida, NaN o lease desmesurada no crea procedencia.
La lectura usa unidades nativas del climatizador para los ledgers externos.

Una corrección externa reconocida invalida decisiones en vuelo y obliga a releer;
no activa Manual local por error. Nunca concede permisos ni cambia la autoridad
externa. La integración no escribe esos helpers. Los emisores retenidos deben
tener una función explícita: no es permiso para mantener otro controlador normal.

`response_entity` no inicia un aprendiz. Solo añade esfuerzo ya medido cuando
coinciden modo/objetivo y su edad está entre0 y660s, con `b` entre0 y2,5°C.
Se conserva el boost proporcional configurado y el límite total de corrección.
Un registro ausente, vencido o incompatible añade esfuerzo cero; no sustituye la
sonda ambiental, el sesgo base ni las guardas. Estos límites son el contrato del
formato v1, no una calibración universal ni valores aprendidos de otra casa.

## Barrera crítica externa

En Fuentes, `external_cut_entity` recibe JSON `{active, at, released}`. `{}` es la
inicialización inactiva; dato ausente, JSON inválido o tipos ambiguos son estado
desconocido, no autorización. Se bloquean emisiones ordinarias con corte activo
o desconocido. `at/released` se capturan al solicitar la intención y se comparan
otra vez después de colas, persistencia y ACK; una liberación no rejuvenece una
petición antigua. Los timestamps mantienen precisión completa.

El corte crítico externo se combina conservadoramente con el medidor de suministro
y la señal binaria crítica existente. Datos desconocidos no liberan un corte
retenido. Los registros críticos se aceptan solo para la generación correspondiente,
con leases acotadas; no sirven para ocultar una intervención humana.

## Antes del traspaso

Certificar por separado: política de cada fase/presencia, configuración física,
Manual y sus excepciones, gestores retenidos, estado de sesiones y planta,
inventario de todos los emisores y rollback. No desactivar un detector sin
reemplazar sus responsabilidades. Probar orden automática, corrección protectora,
cambio humano, eco tardío, reinicio, corte y liberación.

Las pruebas de protocolo y HA vacío solo acreditan ese ensayo. No prueban el
hardware, el instalador, una UI real ni el resultado de una migración doméstica.
Véanse [ejecución y energía](EXECUTION_ENERGY.md) y [migración](MIGRATION.md).
