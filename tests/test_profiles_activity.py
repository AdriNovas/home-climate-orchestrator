"""Portable strategies and optional activity: boundaries, not household recipes."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta
import unittest

from test_domain import fixture, NOW
from domain.models import Memory, Reading, house_from_dict, PriceInterval
from domain.preferences import ActivityBinding, Preferences
from domain.activity import ActivitySample, resolve_activity
from domain.sources import SourceContract
from domain.strategies import preview
from domain.engine import evaluate, begin_dry
from domain.tariffs import generic_intervals


class ActivityTests(unittest.TestCase):
    def test_no_binding_is_optional_unknown(self):
        self.assertEqual(resolve_activity((), {}, 1000).state, "unknown")

    def test_presence_holds_while_on_without_value_changes(self):
        binding = ActivityBinding("binary_sensor.presence", "presence")
        result = resolve_activity(
            (binding,), {binding.entity: ActivitySample("on", 10, 10)}, 10000
        )
        self.assertEqual(result.state, "occupied")

    def test_quiet_motion_never_confirms_vacancy(self):
        binding = ActivityBinding("binary_sensor.pir", hold_s=100)
        for sample in (
            ActivitySample("off", 500, 500),
            ActivitySample("unavailable", 900, 900),
        ):
            self.assertEqual(
                resolve_activity((binding,), {binding.entity: sample}, 1000).state,
                "unknown",
            )

    def test_motion_hold_survives_off_and_restart_without_extension(self):
        binding = ActivityBinding("binary_sensor.pir", hold_s=100)
        active = resolve_activity(
            (binding,), {binding.entity: ActivitySample("on", 950, 950)}, 1000
        )
        off = {binding.entity: ActivitySample("off", 1001, 1010)}
        self.assertEqual(
            resolve_activity((binding,), off, 1049, active.last_positive).state,
            "occupied",
        )
        self.assertEqual(
            resolve_activity((binding,), off, 1050, active.last_positive).state,
            "unknown",
        )

    def test_republished_cache_does_not_renew_motion(self):
        binding = ActivityBinding("binary_sensor.pir", hold_s=100)
        self.assertEqual(
            resolve_activity(
                (binding,), {binding.entity: ActivitySample("on", 10, 999)}, 1000
            ).state,
            "unknown",
        )

    def test_explicit_presence_vacancy_debounce_and_unknown(self):
        binding = ActivityBinding(
            "binary_sensor.presence", "presence", hold_s=10, vacancy_s=100
        )
        off = {binding.entity: ActivitySample("off", 950, 950)}
        self.assertEqual(resolve_activity((binding,), off, 1000).state, "unknown")
        self.assertEqual(resolve_activity((binding,), off, 1050).state, "vacant")
        self.assertEqual(resolve_activity((binding,), {}, 1050).state, "unknown")

    def test_multi_source_positive_wins_and_missing_presence_prevents_vacancy(self):
        presence = ActivityBinding("binary_sensor.presence", "presence", vacancy_s=0)
        pir = ActivityBinding("binary_sensor.pir", hold_s=100)
        other = ActivityBinding("binary_sensor.other", "presence", vacancy_s=0)
        samples = {
            presence.entity: ActivitySample("off", 10, 10),
            pir.entity: ActivitySample("on", 950, 950),
        }
        self.assertEqual(
            resolve_activity((presence, pir), samples, 1000).state, "occupied"
        )
        samples.pop(pir.entity)
        self.assertEqual(
            resolve_activity((presence, pir), samples, 1000).state, "vacant"
        )
        self.assertEqual(
            resolve_activity((presence, other), samples, 1000).state, "unknown"
        )

    def test_custom_activity_mapping_and_stale_presence(self):
        binding = ActivityBinding(
            "sensor.work", "activity", ("working",), ("idle",), hold_s=120
        )
        self.assertEqual(
            resolve_activity(
                (binding,), {binding.entity: ActivitySample("working", 950, 950)}, 1000
            ).state,
            "occupied",
        )
        presence = ActivityBinding(
            "person.demo", "presence", ("home",), ("not_home",), maximum_age_s=60
        )
        self.assertEqual(
            resolve_activity(
                (presence,), {presence.entity: ActivitySample("not_home", 10, 10)}, 1000
            ).state,
            "unknown",
        )

    def test_future_timestamp_cannot_supply_evidence(self):
        binding = ActivityBinding("sensor.demo", "presence")
        self.assertEqual(
            resolve_activity(
                (binding,), {binding.entity: ActivitySample("on", 1001, 1001)}, 1000
            ).state,
            "unknown",
        )

    def test_binding_validation(self):
        for kwargs in (
            {"kind": "guess"},
            {"active_states": ["unknown"]},
            {"inactive_states": ["on"]},
            {"hold_s": float("nan")},
            {"hold_s": 1.5},
            {"maximum_age_s": True},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ActivityBinding("binary_sensor.demo", **kwargs)


class ProfileTests(unittest.TestCase):
    def scenario(self, strategy="price", delay=600):
        house, snap, _, memories, plants = fixture()
        zone = replace(
            house.zones[0],
            preferences=Preferences(heat_day=21, cool_day=24, heat_flex=2, cool_flex=2),
        )
        house = replace(house, strategy=strategy, zones=(zone,))
        obs = replace(
            snap.zones["0"],
            temperature=Reading(20.3, NOW.timestamp()),
            humidity=Reading(50, NOW.timestamp()),
        )
        snap = replace(snap, zones={"0": obs})
        edge = NOW + timedelta(seconds=delay)
        prices = (
            PriceInterval(NOW - timedelta(hours=1), edge, 0.30),
            PriceInterval(edge, NOW + timedelta(hours=3), 0.05),
        )
        return house, snap, prices, memories, plants

    def test_three_profiles_choose_different_bounded_waits(self):
        for strategy, delay, waiting in (
            ("price", 2400, True),
            ("balanced", 2400, False),
            ("comfort", 600, False),
            ("balanced", 600, True),
        ):
            house, snap, prices, mem, plants = self.scenario(strategy, delay)
            decision = evaluate(house, snap, prices, mem, plants)["0"]
            self.assertEqual(
                decision.reason == "cheaper_thermal_window",
                waiting,
                (strategy, decision),
            )
            self.assertGreaterEqual(decision.heat_goal, 19)
            self.assertEqual(decision.preferred_heat, 21)

    def test_legacy_upgrade_round_trip_unchanged(self):
        house, snap, prices, mem, plants = fixture()
        original = evaluate(house, snap, prices, mem, plants)
        data = asdict(house)
        data.pop("strategy")
        data["zones"][0].pop("preferences")
        data["zones"][0].pop("activity_bindings")
        loaded = house_from_dict(data)
        self.assertEqual(loaded.strategy, "legacy")
        self.assertEqual(evaluate(loaded, snap, prices, {}, {}), original)

    def test_preview_has_no_mutation_of_memory_plants_or_input(self):
        house, snap, prices, mem, plants = self.scenario()
        mem["0"] = Memory(
            dry_until=NOW.timestamp() + 100,
            dry_start=NOW.timestamp() - 10,
            debt_since=123,
            attempts=2,
        )
        before = deepcopy((mem, plants, house, snap))
        result = preview(house, snap, prices, mem, plants)
        self.assertEqual(set(result), {"price", "balanced", "comfort"})
        self.assertEqual((mem, plants, house, snap), before)

    def test_profile_change_cannot_renew_wait(self):
        house, snap, prices, mem, plants = self.scenario()
        first = evaluate(house, snap, prices, mem, plants)["0"]
        deadline = mem["0"].thermal_wait_until
        for strategy in ("comfort", "balanced", "price", "price"):
            evaluate(replace(house, strategy=strategy), snap, prices, mem, plants)
            self.assertEqual(mem["0"].thermal_wait_until, deadline)
        self.assertEqual(first.next_at, deadline)
        later = replace(
            snap,
            now=NOW + timedelta(seconds=601),
            power=Reading(100, NOW.timestamp() + 601),
            zones={
                "0": replace(
                    snap.zones["0"], temperature=Reading(20.3, NOW.timestamp() + 601)
                )
            },
        )
        decision = evaluate(house, later, prices, mem, plants)["0"]
        self.assertEqual(decision.mode, "heat")
        self.assertEqual(decision.heat_goal, 21)

    def test_no_price_flat_price_or_horizon_gap_does_not_defer(self):
        house, snap, _, mem, plants = self.scenario()
        for prices in (
            (),
            (PriceInterval(NOW, NOW + timedelta(hours=3), 0.20),),
            (PriceInterval(NOW, NOW + timedelta(seconds=1), 0.20),),
        ):
            decision = evaluate(house, snap, prices, mem, plants)["0"]
            self.assertEqual(decision.mode, "heat")
            self.assertEqual(decision.heat_goal, 21)

    def test_negative_price_cannot_overheat(self):
        house, snap, _, mem, plants = self.scenario()
        snap = replace(
            snap,
            zones={
                "0": replace(snap.zones["0"], temperature=Reading(22, NOW.timestamp()))
            },
        )
        prices = (PriceInterval(NOW, NOW + timedelta(hours=3), -1),)
        decision = evaluate(house, snap, prices, mem, plants)["0"]
        self.assertIsNone(decision.mode)

    def test_outside_flexibility_and_discomfort_budget_recover(self):
        house, snap, prices, mem, plants = self.scenario()
        for temp, budget in ((18, 0), (20.3, 30)):
            current = replace(
                snap,
                zones={
                    "0": replace(
                        snap.zones["0"], temperature=Reading(temp, NOW.timestamp())
                    )
                },
            )
            mem = {"0": Memory(discomfort_degree_minutes=budget)}
            self.assertEqual(
                evaluate(house, current, prices, mem, plants)["0"].mode, "heat"
            )

    def test_distinct_reports_only_accumulate_discomfort(self):
        house, snap, prices, mem, plants = self.scenario()
        evaluate(house, snap, prices, mem, plants)
        later = replace(snap, now=NOW + timedelta(seconds=60))
        evaluate(house, later, prices, mem, plants)
        self.assertEqual(mem["0"].discomfort_degree_minutes, 0)
        later = replace(
            later,
            zones={
                "0": replace(
                    later.zones["0"], temperature=Reading(20.3, NOW.timestamp() + 60)
                )
            },
        )
        evaluate(house, later, prices, mem, plants)
        self.assertAlmostEqual(mem["0"].discomfort_degree_minutes, 0.7)

    def test_manual_pause_stale_and_minimum_off_all_preserved(self):
        for strategy in ("price", "balanced", "comfort"):
            house, snap, prices, _, _ = self.scenario(strategy)
            obs = replace(snap.zones["0"], temperature=Reading(15, NOW.timestamp()))
            for test, current in (
                ("manual", replace(snap, zones={"0": replace(obs, automatic=False)})),
                ("pause", replace(snap, zones={"0": obs}, paused=True)),
                (
                    "stale",
                    replace(
                        snap, zones={"0": replace(obs, temperature=Reading(15, 1))}
                    ),
                ),
                (
                    "minimum_off",
                    replace(
                        snap, zones={"0": replace(obs, mode_since=NOW.timestamp())}
                    ),
                ),
            ):
                with self.subTest(strategy=strategy, test=test):
                    decision = evaluate(house, current, prices, {}, {})["0"]
                    self.assertNotEqual(decision.mode, "heat", decision)

    def test_room_activity_only_changes_explicit_vacancy_preferences(self):
        house, snap, prices, _, _ = self.scenario("comfort")
        zone = replace(
            house.zones[0],
            preferences=replace(
                house.zones[0].preferences, vacancy_heat_delta=2, vacancy_cool_delta=2
            ),
        )
        house = replace(house, zones=(zone,))
        for activity, expected in (("occupied", 21), ("unknown", 21), ("vacant", 19)):
            obs = replace(snap.zones["0"], activity=activity)
            self.assertEqual(
                evaluate(house, replace(snap, zones={"0": obs}), prices, {}, {})[
                    "0"
                ].heat_goal,
                expected,
            )

    def test_default_flexibility_is_zero_and_legacy_ignores_activity(self):
        house, snap, prices, _, _ = self.scenario()
        zone = replace(
            house.zones[0], preferences=Preferences(heat_day=21, cool_day=24)
        )
        self.assertEqual(
            evaluate(replace(house, zones=(zone,)), snap, prices, {}, {})["0"].mode,
            "heat",
        )
        legacy = replace(house, strategy="legacy")
        before = evaluate(legacy, snap, prices, {}, {})["0"]
        after = evaluate(
            legacy,
            replace(snap, zones={"0": replace(snap.zones["0"], activity="vacant")}),
            prices,
            {},
            {},
        )["0"]
        self.assertEqual(before.heat_goal, after.heat_goal)

    def test_external_targets_remain_external(self):
        house, snap, prices, _, _ = self.scenario()
        zone = replace(house.zones[0], heat_goal_entity="input_number.external")
        obs = replace(snap.zones["0"], heat_goal=Reading(22, NOW.timestamp()))
        decision = evaluate(
            replace(house, zones=(zone,)),
            replace(snap, zones={"0": obs}),
            prices,
            {},
            {},
        )["0"]
        self.assertEqual(decision.heat_goal, 22)
        self.assertEqual(decision.strategy_reason, "external_targets")

    def test_preference_validation_and_roundtrip(self):
        for kwargs in (
            {"heat_flex": float("nan")},
            {"price_wait_s": True},
            {"price_wait_s": 1},
            {"minimum_heat": 34, "maximum_cool": 30},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Preferences(**kwargs)
        house, *_ = self.scenario()
        zone = replace(
            house.zones[0], activity_bindings=(ActivityBinding("binary_sensor.demo"),)
        )
        house = replace(house, zones=(zone,))
        self.assertEqual(house_from_dict(asdict(house)), house)

    def test_cooling_opportunities_use_same_bounded_policy(self):
        for strategy, expected in (
            ("price", None),
            ("balanced", None),
            ("comfort", "cool"),
        ):
            house, snap, prices, memories, plants = self.scenario(strategy)
            observation = replace(
                snap.zones["0"], temperature=Reading(24.7, NOW.timestamp())
            )
            decision = evaluate(
                house, replace(snap, zones={"0": observation}), prices, memories, plants
            )["0"]
            self.assertEqual(decision.mode, expected)
            self.assertEqual(decision.preferred_cool, 24)
            self.assertLessEqual(decision.cool_goal, 26)

    def test_failed_room_does_not_reserve_plant_against_healthy_room(self):
        for strategy in ("price", "balanced", "comfort"):
            house, snap, prices, memories, plants = fixture(2)
            house = replace(house, strategy=strategy)
            snap = replace(
                snap,
                zones={
                    **snap.zones,
                    "0": replace(snap.zones["0"], temperature=Reading(None)),
                },
            )
            decisions = evaluate(house, snap, prices, memories, plants)
            self.assertEqual(decisions["0"].reason, "temperature_stale")
            self.assertEqual(decisions["1"].mode, "heat")


class SourceCurrencyTests(unittest.TestCase):
    def test_origin_missing_old_future_and_receipt_semantics(self):
        self.assertFalse(Reading(20, 1000, 1000, semantics="origin").fresh(1000, 60))
        self.assertFalse(Reading(20, 10, 1000, 10, "origin").fresh(1000, 60))
        self.assertFalse(Reading(20, 1001, 1000, 1001, "origin").fresh(1000, 60))
        self.assertTrue(Reading(20, 990, 1000, 990, "origin").fresh(1000, 60))
        self.assertTrue(Reading(20, 990).fresh(1000, 60))

    def test_source_contract_requires_declared_route(self):
        for kwargs in (
            {"semantics": "origin"},
            {"timestamp_attribute": "at"},
            {
                "semantics": "origin",
                "timestamp_attribute": "at",
                "timestamp_entity": "sensor.clock",
            },
        ):
            with self.assertRaises(ValueError):
                SourceContract(**kwargs)

    def test_currency_explicit_units_and_no_fx(self):
        rows = {
            "intervals": [
                {
                    "start": NOW.isoformat(),
                    "end": (NOW + timedelta(hours=1)).isoformat(),
                    "price": 100,
                }
            ]
        }
        for currency in ("USD", "GBP", "JPY"):
            self.assertEqual(
                generic_intervals(rows, currency + "/MWh", currency)[0].price, 0.1
            )
            self.assertEqual(
                generic_intervals(rows, currency + " cents/kWh", currency)[0].price, 1
            )
        for unit, currency in (
            ("USD/kWh", "EUR"),
            ("cents/kWh", "USD"),
            ("EUR/kWh", "USD"),
        ):
            with self.assertRaises(ValueError):
                generic_intervals(rows, unit, currency)

    def test_mixed_interval_currency_or_units_rejected(self):
        row = {
            "start": NOW.isoformat(),
            "end": (NOW + timedelta(hours=1)).isoformat(),
            "price": 0.1,
        }
        for extra in ({"currency": "GBP"}, {"unit": "USD/MWh"}):
            with self.assertRaises(ValueError):
                generic_intervals({"intervals": [{**row, **extra}]}, "USD/kWh", "USD")


class ProfileHumidityTests(unittest.TestCase):
    def test_independent_and_split_drying_waits_are_bounded(self):
        from test_humidity_strategy import dryer_fixture

        for dedicated in (False, True):
            for strategy in ("price", "balanced", "comfort"):
                house, snap, _, memories, plants = (
                    dryer_fixture() if dedicated else fixture()
                )
                zone_id = "dryer" if dedicated else "0"
                stamp = NOW.timestamp()
                if not dedicated:
                    obs = replace(
                        snap.zones[zone_id],
                        temperature=Reading(21, stamp),
                        humidity=Reading(70, stamp),
                    )
                else:
                    obs = replace(snap.zones[zone_id], humidity=Reading(70, stamp))
                snap = replace(snap, zones={**snap.zones, zone_id: obs})
                house = replace(house, strategy=strategy)
                memories[zone_id] = Memory(
                    high_since=stamp - 900, debt_since=stamp - 900
                )
                edge = NOW + timedelta(seconds=600)
                prices = (
                    PriceInterval(NOW - timedelta(hours=1), edge, 0.5),
                    PriceInterval(edge, NOW + timedelta(hours=4), 0.05),
                )
                decision = evaluate(house, snap, prices, memories, plants)[zone_id]
                with self.subTest(dedicated=dedicated, strategy=strategy):
                    self.assertEqual(
                        decision.reason == "cheaper_complete_window",
                        strategy == "price",
                        decision,
                    )
                    if strategy != "price":
                        self.assertEqual(decision.mode, "dry", decision)
                    missing = evaluate(house, snap, (), memories, plants)[zone_id]
                    self.assertEqual(missing.mode, "dry", missing)

    def test_profile_changes_do_not_renew_owned_humidity_session(self):
        from test_humidity_strategy import dryer_fixture

        house, snap, prices, memories, plants = dryer_fixture()
        stamp = NOW.timestamp()
        memories["dryer"].day = NOW.date().isoformat()
        begin_dry(memories["dryer"], stamp - 100, 10, 60, 1200)
        until = memories["dryer"].dry_until
        snap = replace(
            snap,
            zones={**snap.zones, "dryer": replace(snap.zones["dryer"], mode="dry")},
        )
        for strategy in ("price", "balanced", "comfort", "legacy"):
            decision = evaluate(
                replace(house, strategy=strategy), snap, prices, memories, plants
            )["dryer"]
            self.assertEqual(decision.mode, "dry")
            self.assertEqual(memories["dryer"].dry_until, until)
            self.assertEqual(memories["dryer"].dry_target, 60)
            self.assertEqual(memories["dryer"].attempts, 1)
