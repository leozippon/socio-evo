"""Fixed-price outside suppliers for the academy; no service-provider agents or stock state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.port import ToolResult
from world.economy import SUPPLIER
from world.events import Bedridden
from world.telling import amount, bare, cap, listed, you

if TYPE_CHECKING:
    from world.world import Resident, World


def care_available(world: World, r: Resident) -> bool:
    return r.place == world.config.workplace("hospital").id or (
        isinstance(r.base, Bedridden) and r.place == r.home
    )


def counter_told(world: World, r: Resident) -> list[str]:
    c = world.config
    if r.place == c.workplace("store").id:
        goods = listed([f"{bare(i.name)} ({i.id}) {c.money(i.price)}" for i in c.supplied])
        return [f"The external store is always open, with unlimited supply: {goods}."]
    if r.place == c.workplace("restaurant").id:
        menu = listed([f"{bare(i.name)} ({i.id}) {c.money(i.price)}" for i in c.dishes])
        return [f"The external restaurant is always open. On the menu: {menu}."]
    if r.place == c.workplace("hospital").id:
        return [
            f"External care is always available with seek_care: examination "
            f"{c.money(c.hospital.examination)}, treatment {c.money(c.hospital.treatment)}."
        ]
    return []


def buy(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    thing = world.config.item(args["item"])
    place = world.config.workplace("restaurant" if thing.dish else "store")
    if r.place != place.id:
        return ToolResult(f"You can buy {thing.name} at {place.name}, not here.")
    units = args.get("units", 1)
    if thing.dish and units != 1:
        return ToolResult("One dish at a time.")
    if args.get("for_the_kitchen"):
        return ToolResult("The external restaurant supplies its own kitchen.")
    cost = thing.price * units
    if problem := world.cannot_pay(r, cost):
        return ToolResult(problem)
    world.reckon(r)
    if problem := world.move(thing.id, units, SUPPLIER, r.name, by=r):
        return ToolResult(problem)
    bought = amount(thing, units)
    r.inventory.spend(cost, "bought", f"{bought} from the external service")

    def told(w):
        return (
            f"{cap(you(r.name, w))} bought {bought} from the external service "
            f"for {world.config.money(cost)}."
        )

    world.record_move(
        "buy", told, by=r, item=thing.id, units=units, source=SUPPLIER, target=r.name, money=cost
    )
    if thing.dish:
        world.eat_now(r, thing.id)
    else:
        world.take_in(r, tell=True)
    return ToolResult(
        f"{told(r.name)} {world.body.told('satiety', r.living.satiety)} "
        f"{world.things_told(r)} {world.purse(r)}"
    )


def care(world: World, r: Resident, service: str) -> ToolResult:
    if not world.config.external_services:
        return ToolResult("External care is not available in this town.")
    if not care_available(world, r):
        return ToolResult(
            "Visit the Hospital for external care; bedside care is for the bedridden."
        )
    settings = world.config.hospital
    fee = getattr(settings, service)
    if problem := world.cannot_pay(r, fee):
        return ToolResult(problem)
    world.reckon(r)
    before = r.living.health
    numbers = (
        {
            "satiety": r.living.satiety,
            "energy": r.living.energy,
            "health": before,
            "ill": r.living.ill,
            "night": dict(r.living.night),
        }
        if service == "examination"
        else {
            "restores": settings.restores,
            "before": before,
            "health": min(100, before + settings.restores),
            "ill": r.living.ill,
            "bedridden": r.living.bedridden,
        }
    )
    r.inventory.spend(fee, "paid", f"for an external {service}")
    if service == "treatment":
        world.treat(r, settings.restores)
    result = world.body.examination(r.living)

    def told(w):
        return (
            f"{cap(you(r.name, w))} received an external {service} for {world.config.money(fee)}."
        )

    world.record(
        service,
        told,
        actor=r,
        payload={"patient": r.name, "external": True, "fee": fee, "tax": 0} | numbers,
    )
    return ToolResult(f"{told(r.name)} {result} {world.purse(r)}")
