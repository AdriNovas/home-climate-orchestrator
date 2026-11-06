"""Durable, generation-scoped execution protocol; no Home Assistant dependency.

Callbacks supply a fresh plan, emission, clock and an atomic persistent store.
An ACK is an observed state, not a successful service return. Ambiguity latches
Manual locally; neither restart nor refresh retries an ambiguous start.
"""

from __future__ import annotations

import asyncio
import copy
from uuid import uuid4


class Executor:
    def __init__(
        self,
        house,
        store,
        fresh,
        emit,
        clock,
        enabled=False,
        ack_timeout=30,
        publish=None,
    ):
        self.house, self.store, self.fresh = house, store, fresh
        self.emit, self.clock, self.enabled = emit, clock, enabled
        self.ack_timeout = ack_timeout
        self.publish = publish
        self.state = {
            "generation": 0,
            "critical": False,
            "pending": {},
            "manual": {},
            "owned": {},
        }
        self.locks = {p.id: asyncio.Lock() for p in house.plants}
        self.save_lock = asyncio.Lock()
        self.wake = asyncio.Event()
        self.tasks = set()
        self.off_tasks = {}
        self.last_cut = {}
        self.closed = False
        self.errors = {}
        self.inflight = 0
        self.restored = False

    async def save(self, publish_required=True):
        async with self.save_lock:
            persisted = copy.deepcopy(self.state)
            await self.store.async_save(persisted)
            if self.publish:
                try:
                    await self.publish(persisted)
                    self.errors.pop("journal_publication", None)
                except Exception as err:
                    self.errors["journal_publication"] = type(err).__name__
                    if publish_required:
                        raise

    async def restore(self):
        self.restored = False
        saved = await self.store.async_load()
        if saved is not None:
            if (
                not isinstance(saved, dict)
                or type(saved.get("generation")) is not int
                or any(
                    not isinstance(saved.get(k), dict)
                    for k in ["pending", "manual", "owned"]
                )
                or type(saved.get("critical")) is not bool
            ):
                raise ValueError("Invalid execution journal; control cannot start")
            self.state = saved
        zones = {z.id: z for z in self.house.zones}
        for key, owner in list(self.state["owned"].items()):
            if not isinstance(owner, dict):
                raise ValueError("Invalid ownership record")
            if key not in zones or owner.get("binding") != zones[key].actuator_entity:
                self.state["owned"].pop(key)
        for key, row in list(self.state["pending"].items()):
            if (
                key not in zones
                or not isinstance(row, dict)
                or row.get("binding") != zones[key].actuator_entity
            ):
                self.state["pending"].pop(key)
                self.state["owned"].pop(key, None)
                continue
            if row.get("phase") not in ["acked", "cancelled"]:
                # Observe the echo if it arrives, but never replay an interrupted start.
                row["phase"] = "uncertain"
                self.state["manual"][key] = "restart_unconfirmed"
        self.state["generation"] += 1
        await self.save()
        self.restored = True

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)

        def done(t):
            self.tasks.discard(t)
            if not t.cancelled() and t.exception():
                self.errors["runtime"] = type(t.exception()).__name__

        task.add_done_callback(done)
        return task

    def invalidate(self):
        """Synchronous fence: event callbacks revoke authority before awaiting I/O."""
        self.state["generation"] += 1
        self.wake.set()

    def manual(self, zone, reason="external_command"):
        self.state["manual"][zone] = reason
        if reason not in ["unconfirmed_command", "authority_changed_in_flight"]:
            self.state["owned"].pop(zone, None)
        self.invalidate()

    async def resume(self, zone):
        self.state["manual"].pop(zone, None)
        # Old echoes remain recorded until expiry; a new generation cannot reuse them.
        self.invalidate()
        await self.save()

    def is_automatic(self, zone):
        return zone not in self.state["manual"]

    @staticmethod
    def matches(mode, target, observed_mode, observed_target, tolerance=0.01):
        return mode == observed_mode and (
            target is None
            or observed_target is not None
            and abs(target - observed_target) <= tolerance
        )

    def observe(
        self, zone, mode, target, old_mode, old_target, user=False, external=False
    ):
        """Keep full-state expectations so an unrelated human mode/target is not ACKed."""
        if mode in ["unknown", "unavailable"] or old_mode in [
            None,
            "unknown",
            "unavailable",
        ]:
            self.invalidate()
            return
        if mode == old_mode and target == old_target:
            if user and self.enabled:
                self.manual(zone)
            return
        pending = self.state["pending"].get(zone)
        if not user and pending and self.clock() <= pending.get("expires", 0):
            if any(
                self.matches(x["mode"], x.get("target"), mode, target)
                and self.clock() <= x.get("until", pending["expires"])
                for x in pending.get("expected", [])
            ):
                self.wake.set()
                return
        if external and not user:
            # A retained safety/manual manager may emit a registered correction.
            # Revoke in-flight plans, but do not misclassify that echo as a person.
            self.invalidate()
            return
        if self.enabled:
            self.manual(zone)

    async def _ready(self, zone, decision, certificate):
        if (
            self.closed
            or not self.restored
            or not self.enabled
            or self.state["critical"]
            or self.state["generation"] != certificate[0]
            or not self.is_automatic(zone.id)
        ):
            return False
        snap, decisions = self.fresh(zone.id)
        if snap.external_fence != certificate[1]:
            return False
        if certificate[1] is not None and certificate[2] <= max(certificate[1]):
            return False
        obs = snap.zones[zone.id]
        current = decisions[zone.id]
        same = (
            current.mode == decision.mode
            and current.physical_target == decision.physical_target
            and current.target_only == decision.target_only
        )
        # A completed OFF need not remain the next recommendation. In particular,
        # the loss-of-feedback stop may now yield an OFF display update. The
        # certificate and authority checks still fence the transaction; accepting
        # its observed completion cannot authorize another service call.
        same = same or (
            decision.mode == "off" and obs.mode == "off" and not decision.target_only
        )
        if decision.target_only and (
            decision.mode != "off"
            or obs.mode != "off"
            or decision.physical_target is None
            or zone.independent_drying
        ):
            return False
        if decision.mode == "dry" and current.reason == "dry_ack_pending":
            same = obs.dry_allowed
        owner = self.state["owned"].get(zone.id, {})
        owned_stop = (
            decision.mode == "off"
            and decision.stage == "dry_stop"
            and owner.get("mode") == "dry"
            and owner.get("binding") == zone.actuator_entity
        )
        return (
            (not snap.paused and obs.permitted or owned_stop)
            and obs.automatic
            and zone.enabled
            and same
        )

    async def execute(self, zone, decision, accepted=None):
        """One transaction per plant. Re-evaluate after every wait and persistence."""
        submitted = self.clock()
        certificate = (
            self.state["generation"],
            self.fresh(zone.id)[0].external_fence,
            submitted,
        )
        async with self.locks[zone.plant]:
            if self.clock() - submitted > 30 or not await self._ready(
                zone, decision, certificate
            ):
                return "revoked"
            snap, _ = self.fresh(zone.id)
            obs = snap.zones[zone.id]
            if decision.mode is None:
                return "no_command"
            if self.matches(
                decision.mode,
                decision.physical_target,
                obs.mode,
                obs.setpoint,
                obs.step / 2,
            ):
                return "already_satisfied"
            previous = self.state["pending"].get(zone.id)
            if previous and previous.get("phase") == "uncertain":
                return "unconfirmed_previous"
            row = {
                "id": uuid4().hex,
                "binding": zone.actuator_entity,
                "generation": certificate[0],
                "mode": decision.mode,
                "target": decision.physical_target,
                "expires": self.clock() + self.ack_timeout + 15,
                "phase": "prepared",
                "expected": [],
            }
            # Preserve previous late echoes, without extending their lease.
            if previous and previous.get("expires", 0) > self.clock():
                row["expected"] = previous.get("expected", [])[-2:]
                row["expires"] = max(row["expires"], previous["expires"])
            self.state["pending"][zone.id] = row
            await self.save()
            if not await self._ready(zone, decision, certificate):
                row["phase"] = "cancelled"
                await self.save()
                return "revoked"
            try:
                # Set the target while off, then switch mode. Revalidate before each
                # call. This never boots an appliance with a stale physical target.
                steps = []
                if decision.target_only:
                    steps.append(
                        (
                            "set_temperature",
                            {"temperature": decision.physical_target},
                            "off",
                            decision.physical_target,
                        )
                    )
                elif decision.mode == "off":
                    steps.append(
                        ("set_hvac_mode", {"hvac_mode": "off"}, "off", obs.setpoint)
                    )
                else:
                    if decision.physical_target is not None and (
                        obs.setpoint is None
                        or abs(obs.setpoint - decision.physical_target) >= obs.step / 2
                    ):
                        steps.append(
                            (
                                "set_temperature",
                                {"temperature": decision.physical_target},
                                obs.mode,
                                decision.physical_target,
                            )
                        )
                    if obs.mode != decision.mode:
                        steps.append(
                            (
                                "set_hvac_mode",
                                {"hvac_mode": decision.mode},
                                decision.mode,
                                decision.physical_target
                                if decision.physical_target is not None
                                else obs.setpoint,
                            )
                        )
                for service, data, mode, target in steps:
                    row["expected"].append(
                        {
                            "mode": mode,
                            "target": target,
                            "until": self.clock() + self.ack_timeout + 15,
                        }
                    )
                    row["expected"] = row["expected"][-4:]
                    row["phase"] = "sending"
                    await self.save()
                    if not await self._ready(zone, decision, certificate):
                        row["phase"] = "cancelled"
                        await self.save()
                        return "revoked"
                    # Ownership/deadlines and retry budgets precede the first
                    # physical call, not its delayed echo or the next refresh.
                    if accepted:
                        await accepted(zone, decision)
                        accepted = None
                    if self.clock() > row["expires"] or not await self._ready(
                        zone, decision, certificate
                    ):
                        row["phase"] = "cancelled"
                        await self.save()
                        return "revoked"
                    self.inflight += 1
                    try:
                        await asyncio.wait_for(
                            self.emit(zone, service, data, row["id"]),
                            timeout=self.ack_timeout,
                        )
                    finally:
                        self.inflight -= 1
                    if not await self._ready(zone, decision, certificate):
                        row["phase"] = "uncertain"
                        self.state["manual"].setdefault(
                            zone.id, "authority_changed_in_flight"
                        )
                        await self.save()
                        if self.state["critical"]:
                            await self._off(zone)
                        return "revoked_after_send"
                    # Intermediate target ACK before starting the compressor.
                    if not await self._wait_state(zone, mode, target, certificate):
                        raise TimeoutError
                row["phase"] = "acked"
                self.state["owned"][zone.id] = {
                    **self.state["owned"].get(zone.id, {}),
                    "binding": zone.actuator_entity,
                    "mode": decision.mode,
                    "at": self.clock(),
                }
                if decision.mode == "off":
                    self.state["owned"].pop(zone.id, None)
                self.errors.pop(zone.id, None)
                await self.save()
                return "acked"
            except asyncio.CancelledError:
                row["phase"] = "uncertain"
                await self.save()
                raise
            except Exception as err:
                row["phase"] = "uncertain"
                self.errors[zone.id] = type(err).__name__
                self.manual(zone.id, "unconfirmed_command")
                await self.save()
                return "unconfirmed"

    async def _wait_state(self, zone, mode, target, certificate):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.ack_timeout
        while loop.time() < deadline:
            self.wake.clear()
            if self.closed or self.state["generation"] != certificate[0]:
                return False
            snap, _ = self.fresh(zone.id)
            if snap.external_fence != certificate[1]:
                return False
            obs = snap.zones[zone.id]
            if self.matches(mode, target, obs.mode, obs.setpoint, obs.step / 2):
                return True
            try:
                await asyncio.wait_for(
                    self.wake.wait(), timeout=max(0.01, deadline - loop.time())
                )
            except TimeoutError:
                return False
        return False

    async def critical(self, active):
        """Independent off-only workers never wait on ordinary plant/ACK locks."""
        if not self.enabled or self.closed or not self.restored:
            return
        if active != self.state["critical"]:
            self.state["critical"] = active
            self.invalidate()
            await self.save(
                publish_required=False
            )  # A display failure must not block off-only safety.
        if active:
            for zone in self.house.zones:
                task = self.off_tasks.get(zone.id)
                if (
                    zone.actuator_entity
                    and (task is None or task.done())
                    and self.clock() - self.last_cut.get(zone.id, 0) >= 10
                ):
                    self.off_tasks[zone.id] = self.spawn(self._off(zone))

    def owned_certificate(self, zone, owner):
        current = self.state["owned"].get(zone.id, {})
        return (
            owner is not None
            and current.get("id") == owner
            and current.get("binding") == zone.actuator_entity
            and current.get("mode") == "dry"
        )

    async def stop_owned(self, zone):
        owner = self.state["owned"].get(zone.id, {}).get("id")
        task = self.off_tasks.get(zone.id)
        if (
            owner
            and (task is None or task.done())
            and self.clock() - self.last_cut.get(zone.id, 0) >= 10
        ):
            self.off_tasks[zone.id] = self.spawn(self._off(zone, owner))

    async def _off(self, zone, owner=None):
        if not self.state["critical"] and not self.owned_certificate(zone, owner):
            return
        snap, _ = self.fresh(zone.id)
        obs = snap.zones[zone.id]
        if owner is not None and obs.mode not in ["off", "dry"]:
            return
        if obs.mode == "off":
            return
        self.last_cut[zone.id] = self.clock()
        previous = self.state["pending"].get(zone.id, {})
        late = [
            x for x in previous.get("expected", []) if self.clock() <= x.get("until", 0)
        ]
        row = {
            "id": uuid4().hex,
            "binding": zone.actuator_entity,
            "generation": self.state["generation"],
            "mode": "off",
            "target": None,
            "expires": self.clock() + self.ack_timeout + 15,
            "phase": "sending",
            "expected": late[-3:]
            + [
                {
                    "mode": "off",
                    "target": None,
                    "until": self.clock() + self.ack_timeout + 15,
                }
            ],
        }
        self.state["pending"][zone.id] = row
        await self.save(publish_required=False)
        if (
            not self.state["critical"] and not self.owned_certificate(zone, owner)
        ) or self.state["generation"] != row["generation"]:
            row["phase"] = "cancelled"
            await self.save()
            return
        try:
            await asyncio.wait_for(
                self.emit(zone, "set_hvac_mode", {"hvac_mode": "off"}, row["id"]),
                timeout=self.ack_timeout,
            )
            # Service return alone is not an ACK. Next observation reconciles.
            latest, _ = self.fresh(zone.id)
            row["phase"] = (
                "acked" if latest.zones[zone.id].mode == "off" else "uncertain"
            )
            if row["phase"] == "acked":
                self.state["owned"].pop(zone.id, None)
        except Exception as err:
            self.errors[zone.id] = type(err).__name__
            row["phase"] = "uncertain"
        if self.restored:
            await self.save(publish_required=False)

    async def close(self):
        self.closed = True
        self.invalidate()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.restored:
            await self.save(publish_required=False)
