# Decisiones de diseño

## ADR001 · Producto separado del perfil privado

Código, pruebas ficticias y documentación genérica en este repositorio. Viviendas,
sensores, identidades, acceso, histórico y evidencia fuera. Sincronizar toda una
configuración HA privada no es publicar un producto HACS.

## ADR002 · Observación primero, un solo escritor después

0.1 no contiene actuación. Las propuestas no son órdenes aceptadas ni estados de
equipos. Un ejecutor futuro será una frontera explícita, con pruebas de protocolo
y migración por instalación, no un `async_call` añadido al coordinator.

## ADR003 · Confort local no depende del forecast

La temperatura ambiental válida es la referencia; una previsión opcional puede
mejorar anticipación, pero su caída no debe impedir calentar una casa fría.
La falta de una lectura exterior necesaria para una protección sí se comunica.

## ADR004 · Quitar agua no equivale a bajar HR calentando

Evaluar secado mediante temperatura, rocío/humedad absoluta y rebote. Priorizar
temperatura antes de dry; permitir suelo térmico independiente del objetivo
económico para que una subida de confort no haga inalcanzable el secado.
La deuda de humedad no desaparece por entrar en precio caro.

## ADR005 · Evitar órdenes no significa dejar de regular

Equipo con consigna correcta mantiene su rama; no cae a fan/apagado por no haber
nada nuevo que emitir. Corrección estable del sensor interno, esfuerzo transitorio
acotado y cadencia son conceptos distintos. No se impone una consigna alta a todos
los equipos ni se atribuye eficiencia a una idea sin medirla.

## ADR006 · Intervalos completos y calidad explícita

UTC en el núcleo; horarios locales solo en los adaptadores de calendario. Sin
inventar horas futuras. Coste de un bloque entero, no del primer tramo. Unidades
ambiguas y datos viejos son bloqueos diagnosticables, nunca ceros convenientes.

## Pendientes de producto

Ejecutor y bloqueo global entre entradas, adaptadores por tecnología, calendarios
avanzados, objetivos propios de frío/noche por estancia, import/export de perfiles,
aprendizaje robusto de respuesta, virtual climate, reparaciones nativas y pruebas
en segunda vivienda. Ninguno se anuncia como terminado en0.1.
