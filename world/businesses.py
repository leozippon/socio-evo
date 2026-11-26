"""The town's businesses: the Store, the Restaurant's kitchen and the Hospital's surgery.

A business (`Business`) is the trade of one workplace, by the workplace's kind (`BUSINESSES`). Its
keepers are the residents whose occupation works there (`Business.keepers`), and it is theirs:
what it holds stands at its place in holders of its own (`holds`: the Store's shelves; the
kitchen's counter, where the dishes stand ready, and its larder, which it cooks from; the surgery
holds nothing), and what it buys its keeper pays for. It posts prices, one list of them by what
is sold (`World.prices`, by the business's kind, from `starting_prices`), which its keeper sets
with `set_price`: the Store for a unit of each item the supplier sells, the kitchen for a portion
of each dish, the surgery for an examination and a treatment (`FEES`). A price is information
and nothing more: whoever takes a thing from a business's holder is told the price posted for it
(`posted`), and nothing charges anyone; paying is giving the keeper the money. What a business
holds is simply there, whether or not its keeper is: a resident at its place reads what stands
there and at what price (`stores_told`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from world.config import Place, TownConfig
from world.economy import COUNTER, LARDER, SHELVES, add
from world.occupations import OCCUPATIONS
from world.telling import amount, bare, cap, listed

if TYPE_CHECKING:
    from world.world import Resident, World

FEES = ("examination", "treatment")
"""The surgery's services, each with its fee."""


@dataclass(frozen=True)
class Business:
    """The business of the town's workplace of `kind` (see the module docstring): `holds`, its
    holders of things at its place; `sells`, how `set_price` says that something is not among
    what it sells."""

    kind: str
    holds: tuple[str, ...]
    sells: str

    def place(self, config: TownConfig) -> Place:
        return config.workplace(self.kind)

    def keeps(self, occupation: str) -> bool:
        """Whether the occupation `occupation` keeps it: its workplace is of the business's
        kind."""
        return OCCUPATIONS[occupation].workplace == self.kind

    def keepers(self, world: World) -> list[Resident]:
        """The residents who keep it, whose it is."""
        return [r for r in world.residents.values() if self.keeps(r.occupation.id)]

    def prices(self, world: World) -> dict[str, int]:
        """What it sells, each at the price posted now."""
        return world.prices[self.kind]


STORE = Business(kind="store", holds=(SHELVES,), sells="sold at")
KITCHEN = Business(kind="restaurant", holds=(COUNTER, LARDER), sells="on the menu of")
SURGERY = Business(kind="hospital", holds=(), sells="a service of")
BUSINESSES = {business.kind: business for business in (STORE, KITCHEN, SURGERY)}
"""The town's businesses by the kind of their workplace."""
HOLDS = tuple(key for business in BUSINESSES.values() for key in business.holds)
"""Every holder a business keeps, by the name a resident takes from it and gives to it by."""


def keeping(key: str) -> Business | None:
    """The business whose holder `key` is, if it is one's."""
    return next((b for b in BUSINESSES.values() if key in b.holds), None)


def starting_prices(config: TownConfig) -> dict[str, dict[str, int]]:
    """Each business's prices at the start, by its kind, from the configuration: the Store's for
    a unit of each item the supplier sells, the kitchen's for a portion of each dish, in the
    catalogue's order, and the surgery's fees."""
    hospital = config.hospital
    return {
        STORE.kind: {item.id: item.price for item in config.supplied},
        KITCHEN.kind: {dish.id: dish.price for dish in config.dishes},
        SURGERY.kind: {"examination": hospital.examination, "treatment": hospital.treatment},
    }


def priced(config: TownConfig, sold: str) -> str:
    """What is sold under the name `sold`, an item or one of the surgery's services, as a
    sentence names it."""
    return f"the {sold}" if sold in FEES else config.item(sold).name


def posted(world: World, key: str, what: str) -> int | None:
    """The price posted for a unit of `what` where it stands in the holder `key`: its
    business's, if `key` is a business's holder and the business sells it; else none."""
    business = keeping(key)
    return business.prices(world).get(what) if business is not None else None


def _standing(world: World, key: str, state: str, gone: str | None = None) -> str:
    """What stands in the business's holder `key`, to end a sentence: each thing its business
    sells with its price and how many are there (`bread $4 (10 left)`, `stew $20 (2 ready)`),
    one of which none is there told under `gone` (`none left: coat`) or, without it, in its
    place (`none ready`); then whatever else is there, money among it."""
    c, holder = world.config, world.holders[key]
    sold, out, other = [], [], [c.money(holder.money)] if holder.money else []
    for item in c.items:
        units, price = holder.units(item.id), posted(world, key, item.id)
        if price is None:
            other += [amount(item, units)] if units else []
        elif units or gone is None:
            sold.append(f"{bare(item.name)} {c.money(price)} ({units or 'none'} {state})")
        else:
            out.append(bare(item.name))
    told = listed(sold) or "nothing"
    told += f"; {gone}: {listed(out)}" if out else ""
    return told + (f"; also there: {listed(other)}." if other else ".")


def stores_told(world: World, r: Resident) -> list[str]:
    """What `r` reads of the business at the place where it is, whoever it is and whether or not
    a keeper is there: what stands on the Store's shelves and at what price, with what is gone
    from them; the kitchen's menu with the portions ready on its counter, and what its larder
    holds; the surgery's fees. A keeper of the Store reads what is on order besides."""
    c = world.config
    if r.place == STORE.place(c).id:
        told = [f"On the shelves: {_standing(world, SHELVES, 'left', 'none left')}"]
        if STORE.keeps(r.occupation.id) and world.store.pending:
            coming: dict[str, int] = {}
            for item, units, _ in world.store.pending:
                add(coming, str(item), int(units))
            told.append(f"On order from the supplier: {listed(world.listing(coming))}.")
        return told
    if r.place == KITCHEN.place(c).id:
        return [f"On the counter: {_standing(world, COUNTER, 'ready')}", larder_told(world)]
    if r.place == SURGERY.place(c).id:
        fees = SURGERY.prices(world)
        return [
            f"{cap(a_service('examination'))} costs {c.money(fees['examination'])}, "
            f"{a_service('treatment')} {c.money(fees['treatment'])}."
        ]
    return []


def larder_told(world: World) -> str:
    """What the kitchen's larder holds, as anyone at the Restaurant reads it."""
    held = world.held_told(world.holders[LARDER])
    return f"In the larder: {listed(held)}." if held else "The larder is empty."


def a_service(service: str) -> str:
    """One of the surgery's services with its article: `an examination`, `a treatment`."""
    return f"an {service}" if service[0] in "aeiou" else f"a {service}"
