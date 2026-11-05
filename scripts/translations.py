"""Generate checked-in native English/Spanish UI strings from explicit labels."""

import json
import pathlib

ROOT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components/climate_orchestrator"
)
en = {
    "name": "Name",
    "timezone": "Time zone",
    "tariff_type": "Tariff type",
    "entity": "Price sensor",
    "price": "Energy price (EUR/kWh)",
    "weekdays": "Days",
    "start": "Start",
    "end": "End",
    "on_date": "Date exception (optional)",
    "add_another": "Add another price period",
    "plant": "Plant",
    "zone": "Zone",
    "band": "Price band",
    "period": "Price period",
    "temperature_entity": "Reference temperature sensor",
    "humidity_entity": "Humidity sensor",
    "climate_entity": "Underlying climate entity",
    "authority_entity": "Automatic-authority helper (on = automatic)",
    "area": "Real area",
    "labels": "Existing functional labels",
    "bias": "Internal sensor bias (°C)",
    "priority": "Relative priority",
    "allow_dry": "Model drying opportunities",
    "night_allowed": "Allow this zone during sleep",
    "enabled": "Include this zone in proposals",
    "shared_mode": "Shared outdoor unit: one thermal mode",
    "minimum_off_min": "Minimum off (minutes)",
    "minimum_on_min": "Minimum on (minutes)",
    "direction_hold_min": "Minimum direction hold (minutes)",
    "reversal_gap_min": "Minimum between reversals (minutes)",
    "override": "Override daytime heat targets for this zone",
    "power_entity": "Measured active power (W/kW, optional)",
    "outdoor_entity": "Outdoor temperature sensor (optional)",
    "presence_entity": "Occupancy (optional)",
    "control_entity": "Global automatic permission (on = enabled, optional)",
    "heat_day": "Day heating target (°C)",
    "heat_sleep": "Sleep heating target (°C)",
    "cool_day": "Day cooling target (°C)",
    "cool_sleep": "Sleep cooling target (°C)",
    "humidity_start": "Start drying above (%)",
    "humidity_stop": "Finish drying below (%)",
    "upper": "Upper price boundary (exclusive, EUR/kWh)",
}
es = {
    "name": "Nombre",
    "timezone": "Zona horaria",
    "tariff_type": "Tipo de tarifa",
    "entity": "Sensor de precio",
    "price": "Precio de energía (€/kWh)",
    "weekdays": "Días",
    "start": "Inicio",
    "end": "Fin",
    "on_date": "Excepción de fecha (opcional)",
    "add_another": "Añadir otro periodo de precio",
    "plant": "Planta",
    "zone": "Estancia",
    "band": "Tramo de precio",
    "period": "Periodo de precio",
    "temperature_entity": "Sonda de temperatura de referencia",
    "humidity_entity": "Sonda de humedad",
    "climate_entity": "Entidad del equipo climático",
    "authority_entity": "Ayudante de autoridad automática (on = automático)",
    "area": "Área real",
    "labels": "Etiquetas funcionales existentes",
    "bias": "Desfase de la sonda interna (°C)",
    "priority": "Prioridad relativa",
    "allow_dry": "Modelar oportunidades de secado",
    "night_allowed": "Permitir esta estancia durante sueño",
    "enabled": "Incluir esta estancia en las propuestas",
    "shared_mode": "Exterior compartido: un único sentido térmico",
    "minimum_off_min": "Reposo mínimo (minutos)",
    "minimum_on_min": "Marcha mínima (minutos)",
    "direction_hold_min": "Permanencia del sentido (minutos)",
    "reversal_gap_min": "Separación entre inversiones (minutos)",
    "override": "Objetivos diurnos de calor propios para esta estancia",
    "power_entity": "Potencia activa medida (W/kW, opcional)",
    "outdoor_entity": "Temperatura exterior (opcional)",
    "presence_entity": "Ocupación (opcional)",
    "control_entity": "Permiso automático global (on = habilitado, opcional)",
    "heat_day": "Objetivo de calor diurno (°C)",
    "heat_sleep": "Objetivo de calor en sueño (°C)",
    "cool_day": "Objetivo de frío diurno (°C)",
    "cool_sleep": "Objetivo de frío en sueño (°C)",
    "humidity_start": "Iniciar secado por encima de (%)",
    "humidity_stop": "Terminar secado por debajo de (%)",
    "upper": "Límite superior del precio, excluyente (€/kWh)",
}
policy_labels = {
    "modulated_hold_s": (
        "Maximum proposed soft hold (seconds; 0 disables)",
        "Espera suave propuesta máxima (segundos; 0 desactiva)",
    ),
    "extreme_price_enabled": (
        "Model an extreme-price shutdown",
        "Modelar parada por precio extremo",
    ),
    "extreme_price": (
        "Extreme-price entry (EUR/kWh)",
        "Entrada en precio extremo (€/kWh)",
    ),
    "extreme_price_hysteresis": (
        "Extreme-price exit margin (EUR/kWh)",
        "Margen de salida de precio extremo (€/kWh)",
    ),
    "thermal_stable_s": (
        "Required observed stability (seconds)",
        "Estabilidad observada necesaria (segundos)",
    ),
    "thermal_stability_delta": (
        "Maximum stable temperature range (°C)",
        "Rango térmico máximo estable (°C)",
    ),
    "thermal_sample_gap_s": (
        "Maximum stability sample gap (seconds)",
        "Hueco máximo entre muestras estables (segundos)",
    ),
    "start_delta": ("Start deviation (°C)", "Desviación para arrancar (°C)"),
    "hold_delta": ("Maintenance tolerance (°C)", "Tolerancia de mantenimiento (°C)"),
    "overshoot_delta": ("Overshoot protection (°C)", "Protección por sobrepaso (°C)"),
    "proportional_gain": (
        "Recovery proportional gain",
        "Ganancia proporcional de recuperación",
    ),
    "boost_limit": ("Maximum extra effort (°C)", "Empuje adicional máximo (°C)"),
    "correction_limit": (
        "Maximum total compensation (°C)",
        "Compensación total máxima (°C)",
    ),
    "command_interval": (
        "Ordinary command cadence (seconds)",
        "Cadencia de órdenes ordinarias (segundos)",
    ),
    "temperature_fresh_s": (
        "Reference temperature freshness (seconds)",
        "Frescura de temperatura de referencia (segundos)",
    ),
    "humidity_fresh_s": (
        "Humidity freshness (seconds)",
        "Frescura de humedad (segundos)",
    ),
    "internal_fresh_s": (
        "Internal sensor freshness (seconds)",
        "Frescura de sonda interna (segundos)",
    ),
    "dry_floor_day": (
        "Drying temperature floor, day (°C)",
        "Suelo térmico de secado, día (°C)",
    ),
    "dry_floor_sleep": (
        "Drying temperature floor, sleep (°C)",
        "Suelo térmico de secado, sueño (°C)",
    ),
    "dry_margin": ("Drying temperature margin (°C)", "Margen térmico para secado (°C)"),
    "dry_min_outdoor": (
        "Minimum outdoor temperature for drying (°C)",
        "Exterior mínimo para secar (°C)",
    ),
    "dry_min_s": (
        "Normal minimum drying session (seconds)",
        "Mínimo normal de secado (segundos)",
    ),
    "dry_max_s": ("Maximum drying session (seconds)", "Máximo de secado (segundos)"),
    "dry_cooldown_s": (
        "Drying cooldown (seconds)",
        "Descanso entre secados (segundos)",
    ),
    "dry_attempts": (
        "Drying attempts per local day",
        "Intentos de secado por día local",
    ),
    "humidity_stable_s": (
        "Humidity demand persistence (seconds)",
        "Permanencia de demanda de humedad (segundos)",
    ),
    "humidity_recovery_s": (
        "Humidity recovery persistence (seconds)",
        "Permanencia de recuperación de humedad (segundos)",
    ),
    "humidity_deadline_s": (
        "Maximum normal humidity deferral (seconds)",
        "Aplazamiento máximo de humedad normal (segundos)",
    ),
    "service_humidity": (
        "Humidity debt threshold (%)",
        "Umbral de deuda de humedad (%)",
    ),
    "severe_humidity": (
        "Severe humidity threshold (%)",
        "Umbral de humedad severa (%)",
    ),
    "severe_stable_s": (
        "Severe humidity persistence (seconds)",
        "Permanencia de humedad severa (segundos)",
    ),
    "urgent_humidity": ("High humidity threshold (%)", "Umbral de humedad alta (%)"),
    "urgent_stable_s": (
        "High humidity persistence (seconds)",
        "Permanencia de humedad alta (segundos)",
    ),
    "lookahead_s": (
        "Maximum price lookahead (seconds)",
        "Horizonte de espera por precio (segundos)",
    ),
    "improvement": (
        "Minimum useful price improvement (EUR/kWh)",
        "Mejora mínima de precio útil (€/kWh)",
    ),
    "power_limit": (
        "Preventive active-power budget (W)",
        "Presupuesto preventivo de potencia activa (W)",
    ),
    "power_fresh_s": (
        "Active-power freshness (seconds)",
        "Frescura de potencia activa (segundos)",
    ),
}
for key, a, b in [
    (
        "authority_states",
        "States granting automatic authority",
        "Estados que conceden autoridad automática",
    ),
    (
        "heat_goal_entity",
        "External heating goal (optional)",
        "Objetivo externo de calor (opcional)",
    ),
    (
        "cool_goal_entity",
        "External cooling goal (optional)",
        "Objetivo externo de frío (opcional)",
    ),
    (
        "bias_entity",
        "External sensor bias (internal minus reference, °C)",
        "Desfase externo (interna menos referencia, °C)",
    ),
    (
        "internal_entity",
        "Separate internal thermometer (optional)",
        "Sonda interna separada (opcional)",
    ),
    (
        "permission_entity",
        "Zone permission (on = permitted)",
        "Permiso de estancia (on = permitido)",
    ),
    (
        "heat_permission_entity",
        "Heating permission (optional)",
        "Permiso de calor (opcional)",
    ),
    (
        "cool_permission_entity",
        "Cooling permission (optional)",
        "Permiso de frío (opcional)",
    ),
    (
        "dry_permission_entity",
        "Drying permission (optional)",
        "Permiso de secado (opcional)",
    ),
    (
        "critical_entity",
        "External critical cutoff (on = cut all assigned actuators)",
        "Corte crítico externo (on = apagar todos los equipos asignados)",
    ),
    (
        "control_states",
        "States granting global permission",
        "Estados que conceden permiso global",
    ),
    ("presence_states", "States meaning occupied", "Estados que indican ocupación"),
    ("execution_mode", "Operating mode", "Modo de funcionamiento"),
    (
        "exclusive_control",
        "Other automatic controllers are stopped for these actuators",
        "Los demás controladores automáticos de estos equipos están detenidos",
    ),
    ("critical_w", "Critical supply power (W)", "Potencia crítica de suministro (W)"),
    ("critical_s", "Critical persistence (seconds)", "Permanencia crítica (segundos)"),
    ("release_w", "Release below (W)", "Liberar por debajo de (W)"),
    (
        "release_s",
        "Release persistence (seconds)",
        "Permanencia de recuperación (segundos)",
    ),
    ("meter", "Meter (＋ adds a new one)", "Medidor (＋ añade uno nuevo)"),
    (
        "scope_target",
        "What this meter actually measures",
        "Qué mide realmente este contador",
    ),
    (
        "energy_entity",
        "Cumulative energy sensor (Wh/kWh/MWh)",
        "Sensor de energía acumulada (Wh/kWh/MWh)",
    ),
    (
        "fresh_s",
        "Maximum report age (seconds)",
        "Antigüedad máxima del informe (segundos)",
    ),
    (
        "energy_fresh_s",
        "Maximum energy-counter report age (seconds)",
        "Antigüedad máxima del contador de energía (segundos)",
    ),
    (
        "remove",
        "Remove this assignment (never the original sensor/history)",
        "Retirar esta asignación (nunca el sensor/historial original)",
    ),
]:
    en[key], es[key] = a, b
for key, (a, b) in policy_labels.items():
    en[key] = a
    es[key] = b
for key, a, b in [
    ("day_start", "Day starts", "Inicio diurno"),
    ("night_start", "Sleep starts", "Inicio de sueño"),
    ("weekend_day_start", "Weekend day starts", "Inicio diurno en fin de semana"),
    (
        "weekend_night_start",
        "Friday/Saturday sleep starts",
        "Inicio de sueño viernes/sábado",
    ),
]:
    en[key] = a
    es[key] = b
for key, a, b in [
    ("negative", "Negative price", "Precio negativo"),
    ("very_low", "Very low price", "Precio muy bajo"),
    ("low", "Low price", "Precio bajo"),
    ("normal", "Normal price", "Precio normal"),
    ("high", "High price", "Precio alto"),
    ("very_high", "Very high price", "Precio muy alto"),
]:
    en[key] = a
    es[key] = b
steps = {
    "user": ["name", "timezone", "tariff_type"],
    "tariff": ["price", "entity"],
    "period": ["weekdays", "start", "end", "price", "on_date", "add_another"],
    "plant": [
        "name",
        "shared_mode",
        "minimum_off_min",
        "minimum_on_min",
        "direction_hold_min",
        "reversal_gap_min",
    ],
    "zone": [
        "name",
        "plant",
        "temperature_entity",
        "humidity_entity",
        "climate_entity",
        "authority_entity",
        "area",
        "labels",
        "bias",
        "priority",
        "allow_dry",
        "night_allowed",
        "enabled",
    ],
    "policy": list(policy_labels),
    "schedule": [
        "day_start",
        "night_start",
        "weekend_day_start",
        "weekend_night_start",
    ],
    "band": ["band"],
    "band_edit": [
        "upper",
        "heat_day",
        "heat_sleep",
        "cool_day",
        "cool_sleep",
        "humidity_start",
        "humidity_stop",
    ],
    "zone_targets": ["zone"],
    "zone_targets_edit": [
        "override",
        "negative",
        "very_low",
        "low",
        "normal",
        "high",
        "very_high",
    ],
    "sources": ["power_entity", "outdoor_entity", "presence_entity", "control_entity"],
    "fixed_select": ["period"],
    "fixed_edit": ["weekdays", "start", "end", "price", "on_date"],
    "tariff_type": ["tariff_type"],
    "tariff_replace": ["entity", "price"],
}
steps["tariff_period"] = steps["period"]
steps["add_zone"] = steps["zone"]
steps["zone_edit"] = steps["zone"]
steps["plant_edit"] = steps["plant"]
steps["add_plant"] = steps["plant"]
steps["zone"].extend(
    [
        "authority_states",
        "heat_goal_entity",
        "cool_goal_entity",
        "bias_entity",
        "internal_entity",
        "permission_entity",
        "heat_permission_entity",
        "cool_permission_entity",
        "dry_permission_entity",
    ]
)
steps["sources"].extend(["critical_entity", "control_states", "presence_states"])
steps["execution"] = [
    "execution_mode",
    "exclusive_control",
    "critical_w",
    "critical_s",
    "release_w",
    "release_s",
]
steps["energy"] = ["meter"]
steps["meter_edit"] = [
    "name",
    "scope_target",
    "power_entity",
    "energy_entity",
    "fresh_s",
    "energy_fresh_s",
    "remove",
]
titles = {
    "execution": (
        "Execution and supply protection",
        "Ejecución y protección eléctrica",
    ),
    "energy": ("Energy meter assignments", "Asignación de medidores energéticos"),
    "meter_edit": ("Meter and measured scope", "Medidor y ámbito medido"),
    "user": ("Home", "Casa"),
    "tariff": ("Tariff source", "Fuente de tarifa"),
    "period": ("Fixed price period", "Periodo de precio fijo"),
    "plant": ("Climate plant", "Planta climática"),
    "zone": ("Zone", "Estancia"),
    "policy": ("Advanced regulation", "Regulación avanzada"),
    "schedule": ("Use and sleep", "Uso y sueño"),
    "band": ("Price band", "Tramo de precio"),
    "band_edit": ("Targets for this price band", "Objetivos de este tramo"),
    "zone_targets": ("Zone-specific heat targets", "Objetivos de calor por estancia"),
    "zone_targets_edit": ("Daytime heat targets", "Objetivos diurnos de calor"),
    "sources": ("Optional observations", "Medidas opcionales"),
    "fixed_select": ("Edit a fixed price period", "Editar un periodo fijo"),
    "fixed_edit": ("Fixed price period", "Periodo de precio fijo"),
    "tariff_type": ("Replace tariff type", "Cambiar tipo de tarifa"),
    "tariff_replace": ("New tariff source", "Nueva fuente de tarifa"),
    "tariff_period": ("New fixed price period", "Nuevo periodo fijo"),
    "zone_edit": ("Edit zone", "Editar estancia"),
    "plant_edit": ("Edit plant", "Editar planta"),
    "add_zone": ("Add zone", "Añadir estancia"),
    "add_plant": ("Add plant", "Añadir planta"),
}
entities = {
    "meter_power": ("Measured power", "Potencia medida"),
    "meter_energy": ("Measured energy", "Energía medida"),
    "meter_cost_rate": ("Current energy cost rate", "Coste energético instantáneo"),
    "planned_stage": ("Proposed strategy", "Estrategia propuesta"),
    "heat_goal": ("Proposed heating target", "Objetivo de calor previsto"),
    "cool_goal": ("Proposed cooling target", "Objetivo de frío previsto"),
    "humidity_start": ("Drying start threshold", "Umbral de inicio de secado"),
    "humidity_stop": ("Drying end threshold", "Umbral de fin de secado"),
    "physical_target": ("Proposed hardware setpoint", "Consigna física propuesta"),
    "price_degraded": ("Price data degraded", "Precio degradado"),
    "source_degraded": (
        "Climate observations degraded",
        "Medidas climáticas degradadas",
    ),
    "service_blocked": (
        "Persistent humidity service blocked",
        "Servicio de humedad persistente bloqueado",
    ),
}
stages = {
    "idle": ("In band", "En banda"),
    "manual": ("Manual authority", "Autoridad Manual"),
    "waiting": ("Waiting", "En espera"),
    "blocked": ("Blocked", "Bloqueado"),
    "paused": ("Paused", "Pausado"),
    "recovering": ("Would recover temperature", "Recuperaría temperatura"),
    "maintaining": ("Would maintain temperature", "Mantendría temperatura"),
    "holding": ("Would use a relaxed setpoint", "Esperaría con consigna suave"),
    "settling": ("Minimum run settling", "Respetaría marcha mínima"),
    "protect": ("Would stop for protection", "Pararía por protección"),
    "coasting": ("Would coast", "Pasaría a reposo"),
    "dry_ready": ("Drying opportunity", "Oportunidad de secado"),
    "drying": ("Owned drying model", "Modelo de secado propio"),
    "dry_stop": ("Would stop drying", "Terminaría secado"),
    "external": ("Externally controlled drying", "Secado de otro controlador"),
    "reversing": ("Would stop before reversing", "Pararía antes de invertir"),
}
for language, labels, index in [("en", en, 0), ("es", es, 1)]:
    form = {
        step: {
            "title": titles[step][index],
            "data": {field: labels[field] for field in names},
        }
        for step, names in steps.items()
    }
    form["user"]["description"] = (
        "Starts in observation mode. Configure sources, energy meters and optional execution in Settings."
        if language == "en"
        else "Comienza en observación. Configura fuentes, medidores de energía y ejecución opcional en Ajustes."
    )
    form["period"]["description"] = (
        "Equal start/end means 24 hours on the selected days. Date exceptions override matching regular hours."
        if language == "en"
        else "Inicio y fin iguales significan 24 horas en los días elegidos. Las excepciones de fecha sustituyen las horas regulares coincidentes."
    )
    form["sources"]["data"]["power_entity"] = (
        "Total supply/import active power (W/kW), not HVAC power"
        if language == "en"
        else "Potencia activa total del suministro/importación (W/kW), no la del clima"
    )
    form["meter_edit"]["data"]["power_entity"] = (
        "Measured active power for this scope (W/kW)"
        if language == "en"
        else "Potencia activa medida de este ámbito (W/kW)"
    )
    form["finish"] = {
        "title": "Continue" if language == "en" else "Continuar",
        "menu_options": {
            "zone": "Add zone" if language == "en" else "Añadir estancia",
            "plant": "Add plant" if language == "en" else "Añadir planta",
            "create": "Create observation entry"
            if language == "en"
            else "Crear entrada de observación",
        },
    }
    form["init"] = {
        "title": "Settings" if language == "en" else "Ajustes",
        "menu_options": {
            k: titles.get(k, (k, k))[index]
            for k in [
                "policy",
                "schedule",
                "band",
                "zone",
                "zone_targets",
                "add_zone",
                "plant",
                "add_plant",
                "sources",
                "tariff",
                "tariff_type",
                "energy",
                "execution",
            ]
        },
    }
    errors = {
        "invalid_configuration": "Invalid settings or conflicting targets"
        if language == "en"
        else "Ajustes inválidos u objetivos incompatibles",
        "invalid_tariff": "Overlapping or uncovered tariff periods"
        if language == "en"
        else "Periodos solapados o tarifa con huecos",
    }
    data = {
        "title": "Home Climate Orchestrator",
        "config": {
            "step": {
                k: form[k]
                for k in ["user", "tariff", "period", "plant", "zone", "finish"]
            },
            "error": errors,
        },
        "options": {
            "step": {
                k: v for k, v in form.items() if k not in ["user", "period", "finish"]
            },
            "error": errors,
        },
        "entity": {
            "sensor": {
                k: {"name": value[index]}
                for k, value in entities.items()
                if k not in ["price_degraded", "source_degraded", "service_blocked"]
            },
            "binary_sensor": {
                k: {"name": entities[k][index]}
                for k in ["price_degraded", "source_degraded", "service_blocked"]
            },
            "switch": {
                "automatic_control": {
                    "name": "Automatic authority"
                    if language == "en"
                    else "Autoridad automática"
                }
            },
        },
        "selector": {
            "execution_modes": {
                "options": {
                    "shadow": "Observe only" if language == "en" else "Solo observar",
                    "control": "Control assigned devices"
                    if language == "en"
                    else "Controlar equipos asignados",
                }
            },
            "weekdays": {
                "options": dict(
                    zip(
                        map(str, range(7)),
                        [
                            "Monday",
                            "Tuesday",
                            "Wednesday",
                            "Thursday",
                            "Friday",
                            "Saturday",
                            "Sunday",
                        ]
                        if language == "en"
                        else [
                            "Lunes",
                            "Martes",
                            "Miércoles",
                            "Jueves",
                            "Viernes",
                            "Sábado",
                            "Domingo",
                        ],
                    )
                )
            },
            "tariff_types": {
                "options": {
                    "pvpc": "PVPC",
                    "fixed": "Fixed time periods"
                    if language == "en"
                    else "Tramos horarios fijos",
                    "flat": "One fixed price"
                    if language == "en"
                    else "Precio fijo único",
                    "generic": "Generic price intervals"
                    if language == "en"
                    else "Intervalos de sensor genérico",
                }
            },
        },
    }
    data["entity"]["binary_sensor"]["execution_problem"] = {
        "name": "Execution or metering needs attention"
        if language == "en"
        else "Revisar ejecución o medición energética"
    }
    data["options"]["step"]["execution"]["description"] = (
        "Only enable after verifying exclusive control and global permission. Critical cuts include Manual but only the assigned climate entities. No contactors or unrelated loads are controlled."
        if language == "en"
        else "Activar solo tras verificar control exclusivo y permiso global. El corte crítico incluye Manual, solo en las entidades climate asignadas. No controla contactores ni otras cargas."
    )
    data["entity"]["sensor"]["planned_stage"]["state"] = {
        k: v[index] for k, v in stages.items()
    }
    out = ROOT / "translations" / f"{language}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    if language == "en":
        (ROOT / "strings.json").write_text(out.read_text())
