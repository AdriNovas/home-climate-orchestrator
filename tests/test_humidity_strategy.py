"""Moisture goals, standalone ownership and conservative coil transitions."""

from dataclasses import asdict, replace
from datetime import timedelta
import unittest

from test_domain import fixture, NOW
from domain.engine import evaluate, begin_dry, dew_point
from domain.models import (
    Memory,
    Observation,
    Plant,
    PlantMemory,
    Reading,
    Zone,
    house_from_dict,
)


def dryer_fixture(**zone_options):
    house, snap, prices, memories, plants = fixture()
    dryer = Zone(
        "dryer",
        "Independent dryer",
        "dryerplant",
        "sensor.bath_temperature",
        humidity_entity="sensor.bath_humidity",
        humidifier_entity="humidifier.demo",
        allow_dry=True,
        **zone_options,
    )
    house = replace(
        house,
        plants=house.plants
        + (Plant("dryerplant", "Independent compressor", shared_mode=False),),
        zones=house.zones + (dryer,),
    )
    t = NOW.timestamp()
    obs = Observation(
        Reading(18, t),
        Reading(82, t),
        mode="off",
        mode_since=t - 10000,
        setpoint=60,
        supported_modes=("off", "dry"),
        minimum=0,
        maximum=100,
        step=1,
    )
    snap = replace(snap, zones={**snap.zones, "dryer": obs})
    memories["dryer"] = Memory(high_since=t - 1800, severe_since=t - 1800)
    return house, snap, prices, memories, plants


class HumidityTests(unittest.TestCase):
    def test_targets_are_independent_per_room_and_price(self):
        h, s, p, m, pm = fixture(2)
        h = replace(
            h,
            zones=(
                replace(
                    h.zones[0],
                    humidity_start_targets={"normal": 63},
                    humidity_stop_targets={"normal": 57},
                ),
                h.zones[1],
            ),
        )
        d = evaluate(h, s, p, m, pm)
        self.assertEqual((d["0"].humidity_start, d["0"].humidity_stop), (63, 57))
        self.assertEqual((d["1"].humidity_start, d["1"].humidity_stop), (65, 60))

    def test_crossed_humidity_or_unknown_band_rejected(self):
        h, *_ = fixture()
        for values in [
            {"humidity_stop_targets": {"normal": 65}},
            {"humidity_start_targets": {"normal": 60}},
            {"humidity_start_targets": {"missing": 61}},
        ]:
            data = asdict(h)
            data["zones"][0].update(values)
            with self.assertRaises(ValueError):
                house_from_dict(data)
        for value in [True, float("nan"), 91, 34]:
            with self.assertRaises(ValueError):
                replace(h.zones[0], humidity_start_targets={"normal": value})

    def test_heat_and_standalone_drying_are_compatible(self):
        h, s, p, m, pm = dryer_fixture()
        d = evaluate(h, s, p, m, pm)
        self.assertEqual(d["0"].mode, "heat")
        self.assertEqual((d["dryer"].mode, d["dryer"].physical_target), ("dry", 60))

    def test_standalone_does_not_need_outdoor_or_split_dry_floor(self):
        h, s, p, m, pm = dryer_fixture()
        s = replace(s, outdoor=Reading(None))
        self.assertEqual(evaluate(h, s, p, m, pm)["dryer"].stage, "dry_ready")

    def test_unavailable_paused_and_manual_never_start(self):
        for state in ["unavailable", "unknown"]:
            h, s, p, m, pm = dryer_fixture()
            s = replace(
                s, zones={**s.zones, "dryer": replace(s.zones["dryer"], mode=state)}
            )
            self.assertIsNone(evaluate(h, s, p, m, pm)["dryer"].mode)
        for option in ["enabled", "automatic", "paused", "permitted"]:
            h, s, p, m, pm = dryer_fixture()
            if option == "enabled":
                h = replace(h, zones=(h.zones[0], replace(h.zones[1], enabled=False)))
            elif option == "paused":
                s = replace(s, paused=True)
            else:
                s = replace(
                    s,
                    zones={
                        **s.zones,
                        "dryer": replace(s.zones["dryer"], **{option: False}),
                    },
                )
            self.assertIsNone(evaluate(h, s, p, m, pm)["dryer"].mode)

    def test_severe_humidity_wins_over_expensive_price_not_thermal_limits(self):
        h, s, p, m, pm = dryer_fixture(humidity_start_targets={"very_high": 89})
        p = tuple(replace(x, price=0.5) for x in p)
        self.assertEqual(evaluate(h, s, p, m, pm)["dryer"].mode, "dry")
        s = replace(
            s,
            zones={
                **s.zones,
                "dryer": replace(
                    s.zones["dryer"], temperature=Reading(7, NOW.timestamp())
                ),
            },
        )
        self.assertEqual(
            evaluate(h, s, p, m, pm)["dryer"].reason, "dehumidifier_temperature_limit"
        )

    def test_session_freezes_target_despite_tariff_change(self):
        h, s, p, m, pm = dryer_fixture(
            humidity_start_targets={"very_high": 70},
            humidity_stop_targets={"very_high": 65},
        )
        begin_dry(m["dryer"], NOW.timestamp() - 700, 10, 55, 5400)
        s = replace(
            s,
            zones={
                **s.zones,
                "dryer": replace(
                    s.zones["dryer"], mode="dry", humidity=Reading(62, NOW.timestamp())
                ),
            },
        )
        p = tuple(replace(x, price=0.5) for x in p)
        d = evaluate(h, s, p, m, pm)["dryer"]
        self.assertEqual((d.stage, d.physical_target), ("drying", 55))

    def test_maximum_and_external_off_block_same_humidity_episode(self):
        for mode, until in [
            ("dry", NOW.timestamp() - 1),
            ("off", NOW.timestamp() + 2000),
        ]:
            h, s, p, m, pm = dryer_fixture()
            begin_dry(m["dryer"], NOW.timestamp() - 6000, 10, 60, 6000)
            m["dryer"].dry_until = until
            s = replace(
                s, zones={**s.zones, "dryer": replace(s.zones["dryer"], mode=mode)}
            )
            evaluate(h, s, p, m, pm)
            self.assertTrue(m["dryer"].dry_episode_blocked)
            self.assertEqual(Memory(**asdict(m["dryer"])).dry_episode_blocked, True)

    def test_standalone_requires_its_own_plant(self):
        h, *_ = dryer_fixture()
        with self.assertRaises(ValueError):
            replace(h, zones=(h.zones[0], replace(h.zones[1], plant="plant")))
        with self.assertRaises(ValueError):
            replace(h.zones[1], climate_entity="climate.other")

    def test_drain_wait_is_separate_from_restart_and_reversal_settings(self):
        h, s, p, m, pm = fixture()
        h = replace(
            h,
            plants=(
                replace(
                    h.plants[0],
                    minimum_off_s=0,
                    direction_hold_s=0,
                    reversal_gap_s=0,
                    coil_drain_s=300,
                ),
            ),
        )
        pm["plant"] = PlantMemory(
            direction="dry",
            since=NOW.timestamp() - 10000,
            last_flip=NOW.timestamp() - 10000,
            last_transition=NOW.timestamp() - 60,
        )
        d = evaluate(h, s, p, m, pm)["0"]
        self.assertEqual(d.reason, "wet_coil_drain_wait")
        self.assertEqual(d.next_at, NOW.timestamp() + 240)
        s = replace(
            s,
            now=NOW + timedelta(seconds=241),
            power=Reading(100, NOW.timestamp() + 241),
        )
        self.assertEqual(evaluate(h, s, p, m, pm)["0"].mode, "heat")

    def test_heating_changes_relative_humidity_not_dew_point(self):
        from math import exp

        # Equal vapour pressure at two room temperatures; no water extracted.
        rh2 = 80 * exp(17.62 * 20 / (243.12 + 20) - 17.62 * 22 / (243.12 + 22))
        self.assertLess(rh2, 80)
        self.assertAlmostEqual(dew_point(20, 80), dew_point(22, rh2), places=8)
