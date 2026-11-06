"""UI configuration: tariff, plants, zones, schedules and editable policies."""

from __future__ import annotations
from dataclasses import asdict, fields
from uuid import uuid4
import copy
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers import area_registry, device_registry, entity_registry
from .const import DOMAIN
from .domain.models import Policy, house_from_dict
from .domain.tariffs import FixedPeriod, validate_fixed
from .validation import validate_sources
from .domain.energy import Meter
from .domain.safety import SupplyProtection


def number(low, high, step=1):
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=low,
            max=high,
            step="any" if step < 0.001 else step,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def entity(domain):
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))


def optional(name, value=vol.UNDEFINED):
    """Pre-fill the UI without reinserting a value the user has just cleared."""
    return vol.Optional(
        name,
        description={"suggested_value": value}
        if value is not vol.UNDEFINED and value is not None
        else {},
    )


def states_selector():
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=["on", "home", "auto", "AI"], multiple=True, custom_value=True
        )
    )


def zone_schema(plants, defaults=None):
    d = defaults or {}
    schema = {
        vol.Required("name", default=d.get("name", "")): str,
        vol.Required(
            "plant", default=d.get("plant", plants[0]["id"])
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[{"value": p["id"], "label": p["name"]} for p in plants]
            )
        ),
        vol.Required(
            "temperature_entity", default=d.get("temperature_entity", vol.UNDEFINED)
        ): entity("sensor"),
        optional("humidity_entity", d.get("humidity_entity", vol.UNDEFINED)): entity(
            "sensor"
        ),
        optional("climate_entity", d.get("climate_entity", vol.UNDEFINED)): entity(
            "climate"
        ),
        optional(
            "humidifier_entity", d.get("humidifier_entity", vol.UNDEFINED)
        ): entity("humidifier"),
        optional("authority_entity", d.get("authority_entity", vol.UNDEFINED)): entity(
            [
                "input_boolean",
                "binary_sensor",
                "switch",
                "input_select",
                "select",
                "schedule",
            ]
        ),
        vol.Required(
            "authority_states", default=list(d.get("authority_states", ["on"]))
        ): states_selector(),
        **{
            optional(n, d.get(n, vol.UNDEFINED)): entity(domains)
            for n, domains in [
                ("heat_goal_entity", ["sensor", "input_number", "number"]),
                ("cool_goal_entity", ["sensor", "input_number", "number"]),
                ("off_goal_entity", ["sensor", "input_number", "number"]),
                ("dry_floor_entity", ["sensor", "input_number", "number"]),
                ("bias_entity", ["sensor", "input_number", "number"]),
                ("internal_entity", "sensor"),
                ("response_entity", ["input_text", "sensor"]),
                ("expected_ledger_entity", ["input_text", "sensor"]),
                ("critical_ledger_entity", ["input_text", "sensor"]),
                (
                    "permission_entity",
                    ["binary_sensor", "input_boolean", "switch", "schedule"],
                ),
                (
                    "heat_permission_entity",
                    ["binary_sensor", "input_boolean", "schedule"],
                ),
                (
                    "cool_permission_entity",
                    ["binary_sensor", "input_boolean", "schedule"],
                ),
                (
                    "dry_permission_entity",
                    ["binary_sensor", "input_boolean", "schedule"],
                ),
                (
                    "thermal_presence_entity",
                    ["binary_sensor", "input_boolean", "schedule"],
                ),
            ]
        },
        optional("area", d.get("area", vol.UNDEFINED)): selector.AreaSelector(),
        optional("labels", list(d.get("labels", []))): selector.LabelSelector(
            selector.LabelSelectorConfig(multiple=True)
        ),
        vol.Required("bias", default=d.get("bias", 0)): number(-4, 4, 0.5),
        vol.Required("priority", default=d.get("priority", 1)): number(0.1, 10, 0.1),
        vol.Required("allow_dry", default=d.get("allow_dry", False)): bool,
        vol.Required(
            "require_internal_feedback",
            default=d.get("require_internal_feedback", False),
        ): bool,
        vol.Required(
            "feedback_loss_action", default=d.get("feedback_loss_action", "hold")
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=["hold", "stop"], translation_key="feedback_loss_actions"
            )
        ),
        vol.Required(
            "mode_permission_loss_action",
            default=d.get("mode_permission_loss_action", "hold"),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=["hold", "stop"], translation_key="feedback_loss_actions"
            )
        ),
        vol.Required(
            "dry_pause_action", default=d.get("dry_pause_action", "stop")
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=["stop", "retain_owned"], translation_key="dry_pause_actions"
            )
        ),
        vol.Required("night_allowed", default=d.get("night_allowed", True)): bool,
        vol.Required("enabled", default=d.get("enabled", True)): bool,
        **(
            {
                vol.Required(k, default=d.get(k, value)): number(low, high)
                for k, value, low, high in [
                    ("dehumidifier_min_s", 600, 180, 86400),
                    ("dehumidifier_max_s", 5400, 180, 86400),
                    ("dehumidifier_cooldown_s", 1200, 180, 86400),
                    ("dehumidifier_min_temperature", 10, 0, 40),
                    ("dehumidifier_max_temperature", 32, 0, 40),
                ]
            }
            if d.get("humidifier_entity")
            else {}
        ),
    }
    return vol.Schema(schema)


def plant_schema(defaults=None):
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required("name", default=d.get("name", "")): str,
            vol.Required("shared_mode", default=d.get("shared_mode", True)): bool,
            **{
                vol.Required(key, default=d.get(key, base)): number(0, 1440)
                for key, base in [
                    ("minimum_off_min", 20),
                    ("minimum_on_min", 20),
                    ("direction_hold_min", 60),
                    ("reversal_gap_min", 120),
                    ("coil_drain_min", 5),
                ]
            },
        }
    )


def plant_data(data, identity=None):
    return {
        "id": identity or uuid4().hex,
        "name": data["name"],
        "shared_mode": data.get("shared_mode", True),
        **{
            name + "_s": int(data.get(name + "_min", base) * 60)
            for name, base in [
                ("minimum_off", 20),
                ("minimum_on", 20),
                ("direction_hold", 60),
                ("reversal_gap", 120),
                ("coil_drain", 5),
            ]
        },
    }


BASIC_ZONE_FIELDS = {
    "name",
    "plant",
    "climate_entity",
    "humidifier_entity",
    "temperature_entity",
    "humidity_entity",
    "area",
    "labels",
}


def split_schema(plants, defaults=None, *, required_climate=True):
    """Only everyday bindings in the initial form; advanced policy stays optional."""
    d = defaults or {}
    binding = "humidifier_entity" if d.get("humidifier_entity") else "climate_entity"
    schema = {
        optional("name", d.get("name", "")): str,
        (
            vol.Required(binding, default=d.get(binding, vol.UNDEFINED))
            if required_climate
            else optional(binding, d.get(binding, vol.UNDEFINED))
        ): entity("humidifier" if binding == "humidifier_entity" else "climate"),
        vol.Required(
            "temperature_entity", default=d.get("temperature_entity", vol.UNDEFINED)
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
        optional(
            "humidity_entity", d.get("humidity_entity", vol.UNDEFINED)
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
        ),
        vol.Required(
            "plant", default=d.get("plant", plants[0]["id"])
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[{"value": p["id"], "label": p["name"]} for p in plants]
            )
        ),
        optional("area", d.get("area", vol.UNDEFINED)): selector.AreaSelector(),
        optional("labels", list(d.get("labels", []))): selector.LabelSelector(
            selector.LabelSelectorConfig(multiple=True)
        ),
    }
    return vol.Schema(schema)


def split_data(hass, data, existing=None):
    """Infer only registry-backed metadata, never identity from a room name."""
    zone = {**(existing or {}), **data}
    registry = entity_registry.async_get(hass)
    climate = data.get("humidifier_entity") or data.get("climate_entity")
    source = registry.async_get(climate) if climate else None
    device = (
        device_registry.async_get(hass).async_get(source.device_id) if source else None
    )
    if not zone.get("area"):
        area = (source.area_id if source else None) or (
            device.area_id if device else None
        )
        if area:
            zone["area"] = area
    if not str(zone.get("name", "")).strip():
        state = hass.states.get(climate) if climate else None
        zone["name"] = (source.name or source.original_name) if source else None
        zone["name"] = zone["name"] or (
            device.name_by_user or device.name if device else None
        )
        zone["name"] = zone["name"] or (state.name if state else None)
        area = (
            area_registry.async_get(hass).async_get_area(zone.get("area"))
            if zone.get("area")
            else None
        )
        zone["name"] = zone["name"] or (area.name if area else None) or ""
    zone["name"] = str(zone["name"]).strip()
    return zone


def split_errors(hass, profile, data, identity=None):
    """Validate selected existing entities without requiring them to be online."""
    errors = {}
    registry = entity_registry.async_get(hass)
    for key, domain, units in [
        ("climate_entity", "climate", None),
        ("humidifier_entity", "humidifier", None),
        ("temperature_entity", "sensor", {"°C", "°F"}),
        ("humidity_entity", "sensor", {"%"}),
    ]:
        source = data.get(key)
        if not source:
            continue
        state = hass.states.get(source)
        if not isinstance(source, str) or source.split(".")[0] != domain:
            errors[key] = "invalid_source"
        elif state is None and registry.async_get(source) is None:
            errors[key] = "entity_not_found"
        elif (
            units
            and state
            and state.attributes.get("unit_of_measurement") not in (None, *units)
        ):
            errors[key] = "invalid_unit"
    humidifier = hass.states.get(data.get("humidifier_entity", ""))
    if humidifier and humidifier.attributes.get("device_class") != "dehumidifier":
        errors["humidifier_entity"] = "not_dehumidifier"
    if data.get("humidifier_entity") and any(
        z.get("humidifier_entity") == data["humidifier_entity"] and z["id"] != identity
        for z in profile["house"]["zones"]
    ):
        errors["humidifier_entity"] = "already_configured"
    if data.get("climate_entity") and any(
        z.get("climate_entity") == data["climate_entity"] and z["id"] != identity
        for z in profile["house"]["zones"]
    ):
        errors["climate_entity"] = "already_configured"
    if not data.get("name"):
        errors["name"] = "name_required"
    return errors


def dehumidifier_schema(defaults=None):
    d = defaults or {}
    return vol.Schema(
        {
            optional("name", d.get("name", "")): str,
            vol.Required(
                "humidifier_entity", default=d.get("humidifier_entity", vol.UNDEFINED)
            ): entity("humidifier"),
            vol.Required(
                "temperature_entity", default=d.get("temperature_entity", vol.UNDEFINED)
            ): entity("sensor"),
            vol.Required(
                "humidity_entity", default=d.get("humidity_entity", vol.UNDEFINED)
            ): entity("sensor"),
            optional("area", d.get("area", vol.UNDEFINED)): selector.AreaSelector(),
            optional("labels", list(d.get("labels", []))): selector.LabelSelector(
                selector.LabelSelectorConfig(multiple=True)
            ),
            vol.Required("enabled", default=d.get("enabled", False)): bool,
        }
    )


def append_dehumidifier(profile, zone):
    plant = uuid4().hex
    profile["house"]["plants"].append(
        {
            "id": plant,
            "name": zone["name"],
            "shared_mode": False,
            "minimum_on_s": 600,
            "minimum_off_s": 1200,
            "direction_hold_s": 0,
            "reversal_gap_s": 0,
            "coil_drain_s": 0,
        }
    )
    profile["house"]["zones"].append(
        {"id": uuid4().hex, **zone, "plant": plant, "allow_dry": True}
    )


class ClimateFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.profile = {"house": {"plants": [], "zones": []}, "tariff": {}}

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input:
            from zoneinfo import ZoneInfo

            try:
                ZoneInfo(user_input["timezone"])
                self.profile["house"].update(
                    name=user_input["name"], timezone=user_input["timezone"]
                )
                self.profile["tariff"]["type"] = user_input["tariff_type"]
                return await self.async_step_tariff()
            except (ValueError, KeyError):
                errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): str,
                    vol.Required("timezone", default=self.hass.config.time_zone): str,
                    vol.Required(
                        "tariff_type", default="pvpc"
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["pvpc", "fixed", "flat", "generic"],
                            translation_key="tariff_types",
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_tariff(self, user_input=None):
        mode = self.profile["tariff"]["type"]
        if mode == "fixed":
            return await self.async_step_period(user_input)
        if user_input:
            self.profile["tariff"].update(user_input)
            return await self.async_step_plant()
        schema = (
            vol.Schema({vol.Required("price"): number(-10, 10, 0.00001)})
            if mode == "flat"
            else vol.Schema({vol.Required("entity"): entity("sensor")})
        )
        return self.async_show_form(step_id="tariff", data_schema=schema)

    async def async_step_period(self, user_input=None):
        errors = {}
        if user_input:
            data = {k: v for k, v in user_input.items() if k != "add_another"}
            data["weekdays"] = tuple(int(x) for x in data["weekdays"])
            try:
                FixedPeriod(**data)
                rows = self.profile["tariff"].get("periods", []) + [data]
                if not user_input.get("add_another"):
                    validate_fixed(
                        tuple(FixedPeriod(**x) for x in rows),
                        self.profile["house"]["timezone"],
                    )
                self.profile["tariff"]["periods"] = rows
                return (
                    await self.async_step_period()
                    if user_input.get("add_another")
                    else await self.async_step_plant()
                )
            except (ValueError, TypeError):
                errors["base"] = "invalid_tariff"
        return self.async_show_form(
            step_id="period",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "weekdays", default=[str(x) for x in range(7)]
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[str(x) for x in range(7)],
                            multiple=True,
                            translation_key="weekdays",
                        )
                    ),
                    vol.Required("start", default="00:00:00"): selector.TimeSelector(),
                    vol.Required("end", default="00:00:00"): selector.TimeSelector(),
                    vol.Required("price"): number(-10, 10, 0.00001),
                    vol.Optional("on_date"): selector.DateSelector(),
                    vol.Required("add_another", default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_plant(self, user_input=None):
        if user_input:
            self.profile["house"]["plants"].append(plant_data(user_input))
            return await self.async_step_split()
        return self.async_show_form(
            step_id="plant",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): str,
                    vol.Required("shared_mode", default=True): bool,
                }
            ),
        )

    async def async_step_split(self, user_input=None):
        errors = {}
        if user_input is not None:
            zone = split_data(self.hass, user_input)
            errors = split_errors(self.hass, self.profile, zone)
            if not errors:
                candidate = copy.deepcopy(self.profile)
                candidate["house"]["zones"].append({"id": uuid4().hex, **zone})
                try:
                    house_from_dict(candidate["house"])
                    validate_sources(self.hass, candidate)
                    self.profile = candidate
                    return await self.async_step_finish()
                except (ValueError, TypeError):
                    errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="split",
            data_schema=split_schema(self.profile["house"]["plants"], user_input),
            errors=errors,
        )

    async def async_step_zone(self, user_input=None):
        errors = {}
        if user_input:
            zone = {"id": uuid4().hex, **user_input}
            candidate = copy.deepcopy(self.profile)
            candidate["house"]["zones"].append(zone)
            try:
                house_from_dict(candidate["house"])
                self.profile = candidate
                return await self.async_step_finish()
            except (ValueError, TypeError):
                errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="zone",
            data_schema=zone_schema(self.profile["house"]["plants"]),
            errors=errors,
        )

    async def async_step_finish(self, user_input=None):
        return self.async_show_menu(
            step_id="finish", menu_options=["split", "dehumidifier", "plant", "create"]
        )

    async def async_step_dehumidifier(self, user_input=None):
        errors = {}
        if user_input is not None:
            zone = split_data(self.hass, user_input)
            errors = split_errors(self.hass, self.profile, zone)
            if not errors:
                candidate = copy.deepcopy(self.profile)
                append_dehumidifier(candidate, zone)
                try:
                    house_from_dict(candidate["house"])
                    validate_sources(self.hass, candidate)
                    self.profile = candidate
                    return await self.async_step_finish()
                except (ValueError, TypeError):
                    errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="dehumidifier",
            data_schema=dehumidifier_schema(user_input),
            errors=errors,
        )

    async def async_step_create(self, user_input=None):
        house_from_dict(self.profile["house"])
        return self.async_create_entry(
            title=self.profile["house"]["name"], data=self.profile
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ClimateOptions(config_entry)


class ClimateOptions(config_entries.OptionsFlow):
    def __init__(self, entry):
        self._entry = entry
        self.profile = copy.deepcopy({**entry.data, **entry.options})
        self._valid_profile = copy.deepcopy(self.profile)
        self.selection = None

    def save(self):
        try:
            house_from_dict(self.profile["house"])
            validate_sources(self.hass, self.profile)
        except (ValueError, TypeError):
            self.profile = copy.deepcopy(self._valid_profile)
            raise
        self._valid_profile = copy.deepcopy(self.profile)
        return self.async_create_entry(title="", data=self.profile)

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["splits", "plants", "comfort", "energy", "system"],
        )

    async def async_step_splits(self, user_input=None):
        return self.async_show_menu(
            step_id="splits",
            menu_options=["add_split", "add_dehumidifier", "zone", "zone_targets"],
        )

    async def async_step_add_dehumidifier(self, user_input=None):
        errors = {}
        if user_input is not None:
            zone = split_data(self.hass, user_input)
            errors = split_errors(self.hass, self.profile, zone)
            if not errors:
                append_dehumidifier(self.profile, zone)
                try:
                    return self.save()
                except (ValueError, TypeError):
                    errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="add_dehumidifier",
            data_schema=dehumidifier_schema(user_input),
            errors=errors,
        )

    async def async_step_plants(self, user_input=None):
        return self.async_show_menu(
            step_id="plants", menu_options=["plant", "add_plant"]
        )

    async def async_step_comfort(self, user_input=None):
        return self.async_show_menu(
            step_id="comfort",
            menu_options=["zone_targets", "band", "schedule", "policy"],
        )

    async def async_step_system(self, user_input=None):
        return self.async_show_menu(
            step_id="system",
            menu_options=["sources", "tariff", "tariff_type", "execution"],
        )

    async def async_step_add_split(self, user_input=None):
        errors = {}
        if user_input is not None:
            zone = split_data(self.hass, user_input)
            errors = split_errors(self.hass, self.profile, zone)
            if not errors:
                self.profile["house"]["zones"].append({"id": uuid4().hex, **zone})
                try:
                    return self.save()
                except (ValueError, TypeError):
                    errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="add_split",
            data_schema=split_schema(self.profile["house"]["plants"], user_input),
            errors=errors,
        )

    async def async_step_add_zone(self, user_input=None):
        errors = {}
        if user_input:
            self.profile["house"]["zones"].append({"id": uuid4().hex, **user_input})
            try:
                return self.save()
            except ValueError:
                errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="add_zone",
            data_schema=zone_schema(self.profile["house"]["plants"]),
            errors=errors,
        )

    async def async_step_add_plant(self, user_input=None):
        if user_input:
            self.profile["house"]["plants"].append(plant_data(user_input))
            return self.save()
        return self.async_show_form(step_id="add_plant", data_schema=plant_schema())

    async def async_step_zone_targets(self, user_input=None):
        if user_input:
            self.selection = user_input["zone"]
            self.target_table = user_input.get("target_table", "heat_targets")
            if self.target_table not in [
                "heat_targets",
                "cool_targets",
                "heat_sleep_targets",
                "cool_sleep_targets",
                "humidity_start_targets",
                "humidity_stop_targets",
            ]:
                return self.async_abort(reason="invalid_configuration")
            return await self.async_step_zone_targets_edit()
        return self.async_show_form(
            step_id="zone_targets",
            data_schema=vol.Schema(
                {
                    vol.Required("zone"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": z["id"], "label": z["name"]}
                                for z in self.profile["house"]["zones"]
                            ]
                        )
                    ),
                    vol.Required(
                        "target_table", default="heat_targets"
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                "heat_targets",
                                "cool_targets",
                                "heat_sleep_targets",
                                "cool_sleep_targets",
                                "humidity_start_targets",
                                "humidity_stop_targets",
                            ],
                            translation_key="target_tables",
                        )
                    ),
                }
            ),
        )

    async def async_step_zone_targets_edit(self, user_input=None):
        index = next(
            i
            for i, z in enumerate(self.profile["house"]["zones"])
            if z["id"] == self.selection
        )
        z = self.profile["house"]["zones"][index]
        policy = house_from_dict(self.profile["house"]).policy
        table = getattr(self, "target_table", "heat_targets")
        base_field = {
            "heat_targets": "heat_day",
            "cool_targets": "cool_day",
            "heat_sleep_targets": "heat_sleep",
            "cool_sleep_targets": "cool_sleep",
            "humidity_start_targets": "humidity_start",
            "humidity_stop_targets": "humidity_stop",
        }[table]
        errors = {}
        if user_input:
            targets = (
                {b.name: user_input[b.name] for b in policy.bands}
                if user_input["override"]
                else {}
            )
            try:
                candidate = copy.deepcopy(self.profile)
                candidate["house"]["zones"][index][table] = targets
                house_from_dict(candidate["house"])
                self.profile = candidate
                return self.save()
            except ValueError:
                errors["base"] = "invalid_configuration"
        schema = {
            vol.Required("override", default=bool(z.get(table))): bool,
            **{
                vol.Required(
                    b.name, default=z.get(table, {}).get(b.name, getattr(b, base_field))
                ): number(
                    35 if table == "humidity_start_targets" else 30,
                    90 if table == "humidity_start_targets" else 70,
                    1,
                )
                if table.startswith("humidity")
                else number(5, 35, 0.5)
                for b in policy.bands
            },
        }
        return self.async_show_form(
            step_id="zone_targets_edit",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={"name": z["name"]},
        )

    async def async_step_tariff_type(self, user_input=None):
        if user_input:
            self._tariff_draft = {"type": user_input["tariff_type"]}
            return (
                await self.async_step_tariff_period()
                if user_input["tariff_type"] == "fixed"
                else await self.async_step_tariff_replace()
            )
        return self.async_show_form(
            step_id="tariff_type",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "tariff_type", default=self.profile["tariff"]["type"]
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["pvpc", "fixed", "flat", "generic"],
                            translation_key="tariff_types",
                        )
                    )
                }
            ),
        )

    async def async_step_tariff_replace(self, user_input=None):
        if user_input:
            self.profile["tariff"] = {**self._tariff_draft, **user_input}
            return self.save()
        schema = (
            vol.Schema({vol.Required("price"): number(-10, 10, 0.00001)})
            if self._tariff_draft["type"] == "flat"
            else vol.Schema({vol.Required("entity"): entity("sensor")})
        )
        return self.async_show_form(step_id="tariff_replace", data_schema=schema)

    async def async_step_tariff_period(self, user_input=None):
        errors = {}
        if user_input:
            data = {k: v for k, v in user_input.items() if k != "add_another"}
            data["weekdays"] = [int(x) for x in data["weekdays"]]
            try:
                FixedPeriod(**data)
                rows = self._tariff_draft.get("periods", []) + [data]
                if user_input.get("add_another"):
                    self._tariff_draft["periods"] = rows
                    return await self.async_step_tariff_period()
                validate_fixed(
                    tuple(FixedPeriod(**x) for x in rows),
                    self.profile["house"]["timezone"],
                )
                self.profile["tariff"] = {**self._tariff_draft, "periods": rows}
                return self.save()
            except (ValueError, TypeError):
                errors["base"] = "invalid_tariff"
        schema = {
            vol.Required(
                "weekdays", default=[str(x) for x in range(7)]
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[str(x) for x in range(7)],
                    multiple=True,
                    translation_key="weekdays",
                )
            ),
            vol.Required("start", default="00:00:00"): selector.TimeSelector(),
            vol.Required("end", default="00:00:00"): selector.TimeSelector(),
            vol.Required("price"): number(-10, 10, 0.00001),
            vol.Optional("on_date"): selector.DateSelector(),
            vol.Required("add_another", default=False): bool,
        }
        return self.async_show_form(
            step_id="tariff_period", data_schema=vol.Schema(schema), errors=errors
        )

    async def async_step_policy(self, user_input=None):
        errors = {}
        values = asdict(house_from_dict(self.profile["house"]).policy)
        if user_input:
            try:
                self.profile["house"]["policy"] = {
                    **self.profile["house"].get("policy", {}),
                    **user_input,
                }
                return self.save()
            except (ValueError, TypeError):
                errors["base"] = "invalid_configuration"
        names = [f.name for f in fields(Policy) if f.name != "bands"]
        return self.async_show_form(
            step_id="policy",
            data_schema=vol.Schema(
                {
                    vol.Required(n, default=values[n]): bool
                    if isinstance(values[n], bool)
                    else number(
                        -20 if n == "dry_min_outdoor" else 0,
                        100000,
                        0.1 if isinstance(values[n], float) else 1,
                    )
                    for n in names
                }
            ),
            errors=errors,
        )

    async def async_step_schedule(self, user_input=None):
        errors = {}
        house = house_from_dict(self.profile["house"])
        if user_input:
            try:
                self.profile["house"].update(user_input)
                return self.save()
            except ValueError:
                errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="schedule",
            data_schema=vol.Schema(
                {
                    vol.Required(n, default=getattr(house, n)): selector.TimeSelector()
                    for n in [
                        "day_start",
                        "night_start",
                        "weekend_day_start",
                        "weekend_night_start",
                    ]
                }
            ),
            errors=errors,
        )

    async def async_step_band(self, user_input=None):
        bands = [asdict(b) for b in house_from_dict(self.profile["house"]).policy.bands]
        if user_input:
            self.selection = user_input["band"]
            return await self.async_step_band_edit()
        return self.async_show_form(
            step_id="band",
            data_schema=vol.Schema(
                {
                    vol.Required("band"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[b["name"] for b in bands]
                        )
                    )
                }
            ),
        )

    async def async_step_band_edit(self, user_input=None):
        bands = [asdict(b) for b in house_from_dict(self.profile["house"]).policy.bands]
        index = next(i for i, b in enumerate(bands) if b["name"] == self.selection)
        row = bands[index]
        errors = {}
        if user_input:
            bands[index].update(user_input)
            try:
                self.profile["house"].setdefault("policy", {})["bands"] = bands
                return self.save()
            except ValueError:
                errors["base"] = "invalid_configuration"
        names = [
            "heat_day",
            "heat_sleep",
            "cool_day",
            "cool_sleep",
            "humidity_start",
            "humidity_stop",
        ] + (["upper"] if row["upper"] is not None else [])
        return self.async_show_form(
            step_id="band_edit",
            data_schema=vol.Schema(
                {
                    vol.Required(n, default=row[n]): number(
                        -10 if n == "upper" else 5,
                        100,
                        0.00001 if n == "upper" else 0.5,
                    )
                    for n in names
                }
            ),
            errors=errors,
        )

    async def async_step_zone(self, user_input=None):
        if user_input:
            self.selection = user_input["zone"]
            return await self.async_step_zone_settings()
        return self.async_show_form(
            step_id="zone",
            data_schema=vol.Schema(
                {
                    vol.Required("zone"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": z["id"], "label": z["name"]}
                                for z in self.profile["house"]["zones"]
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_zone_settings(self, user_input=None):
        zone = next(
            z for z in self.profile["house"]["zones"] if z["id"] == self.selection
        )
        return self.async_show_menu(
            step_id="zone_settings",
            menu_options=["zone_binding", "zone_targets_menu", "zone_advanced"],
            description_placeholders={"name": zone["name"]},
        )

    async def async_step_zone_binding(self, user_input=None):
        zones = self.profile["house"]["zones"]
        index = next(i for i, z in enumerate(zones) if z["id"] == self.selection)
        errors = {}
        if user_input is not None:
            remaining = {
                k: v for k, v in zones[index].items() if k not in BASIC_ZONE_FIELDS
            }
            zone = split_data(self.hass, user_input, remaining)
            errors = split_errors(self.hass, self.profile, zone, self.selection)
            if not errors:
                zones[index] = zone
                try:
                    return self.save()
                except (ValueError, TypeError):
                    errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="zone_binding",
            data_schema=split_schema(
                self.profile["house"]["plants"], zones[index], required_climate=False
            ),
            errors=errors,
        )

    async def async_step_zone_targets_menu(self, user_input=None):
        zone = next(
            z for z in self.profile["house"]["zones"] if z["id"] == self.selection
        )
        return self.async_show_menu(
            step_id="zone_targets_menu",
            menu_options=(
                []
                if zone.get("humidifier_entity")
                else ["heat_day", "cool_day", "heat_sleep", "cool_sleep"]
            )
            + ["humidity"],
        )

    async def async_step_humidity(self, user_input=None):
        if user_input is not None:
            self.humidity_band = user_input["band"]
            return await self.async_step_humidity_pair()
        bands = house_from_dict(self.profile["house"]).policy.bands
        options = []
        for index, band in enumerate(bands):
            low = bands[index - 1].upper if index else None
            high = band.upper
            label = (
                f"<{high:g}"
                if low is None
                else f"{low:g}+"
                if high is None
                else f"{low:g}–{high:g}"
            )
            options.append({"value": band.name, "label": label + " €/kWh"})
        return self.async_show_form(
            step_id="humidity",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "band",
                        default="normal"
                        if any(b.name == "normal" for b in bands)
                        else bands[0].name,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def async_step_humidity_pair(self, user_input=None):
        index = next(
            i
            for i, z in enumerate(self.profile["house"]["zones"])
            if z["id"] == self.selection
        )
        zone = self.profile["house"]["zones"][index]
        band = next(
            b
            for b in house_from_dict(self.profile["house"]).policy.bands
            if b.name == self.humidity_band
        )
        errors = {}
        if user_input is not None:
            candidate = copy.deepcopy(self.profile)
            target = candidate["house"]["zones"][index]
            for table, key in [
                ("humidity_start_targets", "humidity_start"),
                ("humidity_stop_targets", "humidity_stop"),
            ]:
                cells = target.setdefault(table, {})
                if user_input.get("use_common"):
                    cells.pop(band.name, None)
                else:
                    cells[band.name] = user_input[key]
            try:
                house_from_dict(candidate["house"])
                validate_sources(self.hass, candidate)
                self.profile = candidate
                return self.save()
            except (ValueError, TypeError):
                errors["base"] = "invalid_humidity_pair"
        values = {
            "humidity_start": zone.get("humidity_start_targets", {}).get(
                band.name, band.humidity_start
            ),
            "humidity_stop": zone.get("humidity_stop_targets", {}).get(
                band.name, band.humidity_stop
            ),
        }
        return self.async_show_form(
            step_id="humidity_pair",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "humidity_start", default=values["humidity_start"]
                    ): number(35, 90),
                    vol.Required(
                        "humidity_stop", default=values["humidity_stop"]
                    ): number(30, 70),
                    vol.Required("use_common", default=False): bool,
                }
            ),
            errors=errors,
            description_placeholders={"name": zone["name"]},
        )

    async def async_step_humidity_start(self, user_input=None):
        self.target_table = "humidity_start_targets"
        return await self.async_step_zone_targets_edit()

    async def async_step_humidity_stop(self, user_input=None):
        self.target_table = "humidity_stop_targets"
        return await self.async_step_zone_targets_edit()

    async def async_step_heat_day(self, user_input=None):
        self.target_table = "heat_targets"
        return await self.async_step_zone_targets_edit()

    async def async_step_cool_day(self, user_input=None):
        self.target_table = "cool_targets"
        return await self.async_step_zone_targets_edit()

    async def async_step_heat_sleep(self, user_input=None):
        self.target_table = "heat_sleep_targets"
        return await self.async_step_zone_targets_edit()

    async def async_step_cool_sleep(self, user_input=None):
        self.target_table = "cool_sleep_targets"
        return await self.async_step_zone_targets_edit()

    async def async_step_zone_advanced(self, user_input=None):
        zones = self.profile["house"]["zones"]
        index = next(i for i, z in enumerate(zones) if z["id"] == self.selection)
        errors = {}
        advanced = {
            key: value
            for key, value in zone_schema(
                self.profile["house"]["plants"], zones[index]
            ).schema.items()
            if key.schema not in BASIC_ZONE_FIELDS
        }
        if zones[index].get("humidifier_entity"):
            irrelevant = {
                "bias",
                "require_internal_feedback",
                "feedback_loss_action",
                "mode_permission_loss_action",
                "thermal_presence_entity",
                "off_goal_entity",
                "dry_floor_entity",
                "heat_goal_entity",
                "cool_goal_entity",
                "bias_entity",
                "internal_entity",
                "heat_permission_entity",
                "cool_permission_entity",
                "response_entity",
                "expected_ledger_entity",
                "critical_ledger_entity",
            }
            advanced = {
                key: value
                for key, value in advanced.items()
                if key.schema not in irrelevant
            }
        if user_input is not None:
            keys = {key.schema for key in advanced}
            zones[index] = {
                **{k: v for k, v in zones[index].items() if k not in keys},
                **user_input,
            }
            try:
                return self.save()
            except (ValueError, TypeError):
                errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="zone_advanced", data_schema=vol.Schema(advanced), errors=errors
        )

    async def async_step_zone_edit(self, user_input=None):
        zones = self.profile["house"]["zones"]
        index = next(i for i, z in enumerate(zones) if z["id"] == self.selection)
        errors = {}
        if user_input:
            # Omitted optional selectors mean cleared bindings, not old values.
            optional = {
                "humidity_entity",
                "climate_entity",
                "humidifier_entity",
                "authority_entity",
                "area",
                "labels",
                "heat_goal_entity",
                "cool_goal_entity",
                "off_goal_entity",
                "dry_floor_entity",
                "bias_entity",
                "internal_entity",
                "permission_entity",
                "heat_permission_entity",
                "cool_permission_entity",
                "dry_permission_entity",
                "thermal_presence_entity",
                "response_entity",
                "expected_ledger_entity",
                "critical_ledger_entity",
            }
            zones[index] = {
                **{k: v for k, v in zones[index].items() if k not in optional},
                **user_input,
            }
            try:
                return self.save()
            except ValueError:
                errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="zone_edit",
            data_schema=zone_schema(self.profile["house"]["plants"], zones[index]),
            errors=errors,
        )

    async def async_step_plant(self, user_input=None):
        if user_input:
            self.selection = user_input["plant"]
            return await self.async_step_plant_edit()
        return self.async_show_form(
            step_id="plant",
            data_schema=vol.Schema(
                {
                    vol.Required("plant"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": p["id"], "label": p["name"]}
                                for p in self.profile["house"]["plants"]
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_plant_edit(self, user_input=None):
        plants = self.profile["house"]["plants"]
        index = next(i for i, p in enumerate(plants) if p["id"] == self.selection)
        errors = {}
        p = plants[index]
        if user_input:
            plants[index] = plant_data(user_input, p["id"])
            try:
                return self.save()
            except ValueError:
                errors["base"] = "invalid_configuration"
        defaults = {
            **p,
            **{
                n + "_min": p.get(n + "_s", 300 if n == "coil_drain" else 0) / 60
                for n in [
                    "minimum_off",
                    "minimum_on",
                    "direction_hold",
                    "reversal_gap",
                    "coil_drain",
                ]
            },
        }
        return self.async_show_form(
            step_id="plant_edit", data_schema=plant_schema(defaults), errors=errors
        )

    async def async_step_sources(self, user_input=None):
        errors = {}
        if user_input is not None:
            for name in [
                "power_entity",
                "outdoor_entity",
                "presence_entity",
                "control_entity",
                "critical_entity",
                "external_cut_entity",
            ]:
                self.profile.pop(name, None)
            self.profile.update(user_input)
            try:
                return self.save()
            except ValueError:
                errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="sources",
            data_schema=vol.Schema(
                {
                    optional(n, self.profile.get(n, vol.UNDEFINED)): entity(d)
                    for n, d in [
                        ("power_entity", "sensor"),
                        ("outdoor_entity", "sensor"),
                        (
                            "presence_entity",
                            [
                                "binary_sensor",
                                "input_boolean",
                                "person",
                                "group",
                                "schedule",
                            ],
                        ),
                        (
                            "control_entity",
                            [
                                "input_boolean",
                                "binary_sensor",
                                "switch",
                                "input_select",
                                "select",
                                "schedule",
                            ],
                        ),
                        ("critical_entity", ["binary_sensor", "input_boolean"]),
                        ("external_cut_entity", ["input_text", "sensor"]),
                    ]
                }
                | {
                    vol.Required(
                        n, default=list(self.profile.get(n, ["on"]))
                    ): states_selector()
                    for n in ["control_states", "presence_states"]
                }
            ),
            errors=errors,
        )

    async def async_step_execution(self, user_input=None):
        errors = {}
        policy = SupplyProtection(**self.profile.get("supply_protection", {}))
        if user_input:
            self.profile.update(
                execution_mode=user_input["execution_mode"],
                exclusive_control=user_input["exclusive_control"],
            )
            self.profile["supply_protection"] = {
                key: user_input[key]
                for key in ["critical_w", "critical_s", "release_w", "release_s"]
            }
            try:
                return self.save()
            except (ValueError, TypeError):
                errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="execution",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "execution_mode",
                        default=self.profile.get("execution_mode", "shadow"),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["shadow", "control"],
                            translation_key="execution_modes",
                        )
                    ),
                    vol.Required(
                        "exclusive_control",
                        default=self.profile.get("exclusive_control", False),
                    ): bool,
                    **{
                        vol.Required(k, default=getattr(policy, k)): number(
                            100 if k.endswith("_w") else 1,
                            100000 if k.endswith("_w") else 3600,
                        )
                        for k in ["critical_w", "critical_s", "release_w", "release_s"]
                    },
                }
            ),
            errors=errors,
        )

    async def async_step_energy(self, user_input=None):
        if user_input:
            self.selection = user_input["meter"]
            return await self.async_step_meter_edit()
        return self.async_show_form(
            step_id="energy",
            data_schema=vol.Schema(
                {
                    vol.Required("meter"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[{"value": "new", "label": "＋"}]
                            + [
                                {"value": m["id"], "label": m["name"]}
                                for m in self.profile.get("meters", [])
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_meter_edit(self, user_input=None):
        errors = {}
        meters = self.profile.get("meters", [])
        old = next((m for m in meters if m["id"] == self.selection), {})
        if user_input:
            try:
                rows = [m for m in meters if m["id"] != self.selection]
                if not user_input.get("remove"):
                    scope, _, target = user_input["scope_target"].partition(":")
                    row = asdict(
                        Meter(
                            id=old.get("id", uuid4().hex),
                            name=user_input["name"],
                            scope=scope,
                            target=target,
                            power_entity=user_input.get("power_entity"),
                            energy_entity=user_input.get("energy_entity"),
                            fresh_s=user_input["fresh_s"],
                            energy_fresh_s=user_input.get(
                                "energy_fresh_s", old.get("energy_fresh_s", 86400)
                            ),
                            negative_power_tolerance_w=user_input.get(
                                "negative_power_tolerance_w",
                                old.get("negative_power_tolerance_w", 0),
                            ),
                            include_in_system=user_input.get(
                                "include_in_system", old.get("include_in_system", True)
                            ),
                        )
                    )
                    if row["negative_power_tolerance_w"] == 0:
                        # Keep strict/default profiles compatible with versions
                        # predating the optional meter calibration field.
                        row.pop("negative_power_tolerance_w")
                    rows.append(row)
                self.profile["meters"] = rows
                return self.save()
            except (ValueError, TypeError, KeyError):
                errors["base"] = "invalid_configuration"
        options = [{"value": "house", "label": self.profile["house"]["name"]}] + [
            {"value": kind + ":" + x["id"], "label": x["name"]}
            for kind, key in [("plant", "plants"), ("zone", "zones")]
            for x in self.profile["house"][key]
        ]
        return self.async_show_form(
            step_id="meter_edit",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=old.get("name", "")): str,
                    vol.Required(
                        "scope_target",
                        default=old.get("scope", "house")
                        + (":" + old["target"] if old.get("target") else ""),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    ),
                    optional(
                        "power_entity", old.get("power_entity") or vol.UNDEFINED
                    ): entity("sensor"),
                    optional(
                        "energy_entity",
                        old.get("energy_entity") or vol.UNDEFINED,
                    ): entity("sensor"),
                    vol.Required("fresh_s", default=old.get("fresh_s", 120)): number(
                        10, 86400
                    ),
                    vol.Required(
                        "energy_fresh_s", default=old.get("energy_fresh_s", 86400)
                    ): number(10, 604800),
                    vol.Required("remove", default=False): bool,
                    vol.Required(
                        "include_in_system", default=old.get("include_in_system", True)
                    ): bool,
                    vol.Required(
                        "negative_power_tolerance_w",
                        default=old.get("negative_power_tolerance_w", 0),
                    ): number(0, 20, 0.5),
                }
            ),
            errors=errors,
        )

    async def async_step_tariff(self, user_input=None):
        errors = {}
        mode = self.profile["tariff"]["type"]
        # Fixed schedules use one editable row at a time to keep the native form small.
        if mode == "fixed":
            return await self.async_step_fixed_select(user_input)
        if user_input:
            self.profile["tariff"].update(user_input)
            return self.save()
        schema = (
            vol.Schema(
                {
                    vol.Required(
                        "price", default=self.profile["tariff"].get("price", 0.2)
                    ): number(-10, 10, 0.00001)
                }
            )
            if mode == "flat"
            else vol.Schema(
                {
                    vol.Required(
                        "entity",
                        default=self.profile["tariff"].get("entity", vol.UNDEFINED),
                    ): entity("sensor")
                }
            )
        )
        return self.async_show_form(step_id="tariff", data_schema=schema, errors=errors)

    async def async_step_fixed_select(self, user_input=None):
        if user_input:
            self.selection = int(user_input["period"])
            return await self.async_step_fixed_edit()
        return self.async_show_form(
            step_id="fixed_select",
            data_schema=vol.Schema(
                {
                    vol.Required("period"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "value": str(i),
                                    "label": f"{x['start']}–{x['end']} · {x['price']}",
                                }
                                for i, x in enumerate(self.profile["tariff"]["periods"])
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_fixed_edit(self, user_input=None):
        row = self.profile["tariff"]["periods"][self.selection]
        errors = {}
        if user_input:
            edited = {
                **user_input,
                "weekdays": [int(x) for x in user_input["weekdays"]],
            }
            candidate = copy.deepcopy(self.profile["tariff"]["periods"])
            candidate[self.selection] = edited
            try:
                validate_fixed(
                    tuple(FixedPeriod(**x) for x in candidate),
                    self.profile["house"]["timezone"],
                )
                self.profile["tariff"]["periods"] = candidate
                return self.save()
            except ValueError:
                errors["base"] = "invalid_tariff"
        schema = {
            vol.Required(
                "weekdays", default=[str(x) for x in row["weekdays"]]
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[str(x) for x in range(7)],
                    multiple=True,
                    translation_key="weekdays",
                )
            ),
            vol.Required("start", default=row["start"]): selector.TimeSelector(),
            vol.Required("end", default=row["end"]): selector.TimeSelector(),
            vol.Required("price", default=row["price"]): number(-10, 10, 0.00001),
            optional(
                "on_date", row.get("on_date", vol.UNDEFINED)
            ): selector.DateSelector(),
        }
        return self.async_show_form(
            step_id="fixed_edit", data_schema=vol.Schema(schema), errors=errors
        )
