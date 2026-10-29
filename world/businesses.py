"""The town's businesses: the Store's counter, the Restaurant's kitchen and the Hospital's surgery.

A business (`Business`) is the trade of one workplace, by the workplace's kind (`BUSINESSES`). Its
keeper is the resident whose occupation works there, and it is open while its keeper is at work
there (`Business.serving`). It sells at prices of its own, one list of them by what is sold
(`World.prices`, by the business's kind, from `starting_prices`), which its keeper sets with
`set_price`: the Store a unit of each item the supplier sells, the kitchen a portion of each dish,
the surgery an examination and a treatment (`FEES`). What it sells comes off a holder it keeps at
its place (`holds`: the Store's shelves; the kitchen's larder, which it cooks from, and its
portions); the surgery sells its services and holds nothing. What it takes is the fund's, as the
kind of money `fund`; the daybook counts its sales under `daybook`; and its keeper is paid a sum
(`service`) for each. A resident at its place is told whether it is open and what it sells at
what price, its keeper what it holds even while it is shut (`counter_told`), and the mayor's
report lists what each sells.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from world.config import Place, TownConfig
from world.economy import LARDER, PORTIONS, SHELVES, add
from world.events import Work
from world.occupations import OCCUPATIONS
from world.telling import bare, cap, listed

if TYPE_CHECKING:
    from world.world import Resident, World

FEES = ("examination", "treatment")
"""The surgery's services, each sold at its fee."""


@dataclass(frozen=True)
class Business:
    """The business of the town's workplace of `kind` (see the module docstring), and its words:
    `opened`, what its keeper's sitting down to work there tells; `closed`, what one there is
    told while it is shut (`{place}` its place's name); `selling`, `kept` and `listing`, what
    heads what it sells and at what price, as one there reads it while it is open, as its
    keeper reads it while it is shut (nothing, if None) and in the report; `sells`, how
    `set_price` says that something is not among what it sells."""

    kind: str
    holds: tuple[str, ...]
    fund: str
    daybook: str
    service: str
    opened: str
    closed: str
    selling: str
    kept: str | None
    listing: str
    sells: str

    def place(self, config: TownConfig) -> Place:
        return config.workplace(self.kind)

    def keeps(self, occupation: str) -> bool:
        """Whether the occupation `occupation` keeps it: its workplace is of the business's
        kind."""
        return OCCUPATIONS[occupation].workplace == self.kind

    def serving(self, world: World) -> Resident | None:
        """Its keeper at work there, while it is open; None while it is shut."""
        place = self.place(world.config).id
        return next(
            (
                r
                for r in world.residents.values()
                if r.place == place and self.keeps(r.occupation.id) and isinstance(r.base, Work)
            ),
            None,
        )

    def prices(self, world: World) -> dict[str, int]:
        """What it sells, each at its price now."""
        return world.prices[self.kind]

    def closed_told(self, config: TownConfig) -> str:
        return self.closed.format(place=cap(self.place(config).name))


STORE = Business(
    kind="store",
    holds=(SHELVES,),
    fund="sale",
    daybook="sales",
    service="sale",
    opened="The counter is open.",
    closed="{place} is closed: nobody is at the counter.",
    selling="At the counter: ",
    kept="On the shelves: ",
    listing="In stock: ",
    sells="sold at",
)
KITCHEN = Business(
    kind="restaurant",
    holds=(LARDER, PORTIONS),
    fund="dish",
    daybook="dishes",
    service="dish",
    opened="The kitchen is open.",
    closed="The kitchen is closed.",
    selling="On the menu: ",
    kept="On the menu: ",
    listing="On the menu: ",
    sells="on the menu of",
)
SURGERY = Business(
    kind="hospital",
    holds=(),
    fund="fee",
    daybook="patients",
    service="patient",
    opened="The surgery is open.",
    closed="The surgery is closed.",
    selling="The surgery is open: ",
    kept=None,
    listing="",
    sells="a service of",
)
BUSINESSES = {business.kind: business for business in (STORE, KITCHEN, SURGERY)}
"""The town's businesses by the kind of their workplace, in the order the report lists them."""


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


def offered(world: World, business: Business) -> str:
    """What `business` sells now and at what price, to end a sentence: the Store each item it
    has left, with how many, and what is sold out; the kitchen each dish, with how many portions
    are ready; the surgery its fees."""
    c, prices = world.config, business.prices(world)
    if business is STORE:
        shelves = world.holders[SHELVES]
        stocked = [
            f"{bare(item.name)} {c.money(prices[item.id])} ({shelves.units(item.id)} left)"
            for item in c.supplied
            if shelves.units(item.id)
        ]
        out = [bare(item.name) for item in c.supplied if not shelves.units(item.id)]
        return f"{listed(stocked) or 'nothing'}" + (f"; sold out: {listed(out)}." if out else ".")
    if business is KITCHEN:
        portions = world.holders[PORTIONS]
        menu = [
            f"{bare(dish.name)} {c.money(prices[dish.id])} "
            f"({portions.units(dish.id) or 'none'} ready)"
            for dish in c.dishes
        ]
        return f"{listed(menu)}."
    return (
        f"an examination costs {c.money(prices['examination'])}, a treatment "
        f"{c.money(prices['treatment'])}."
    )


def counter_told(world: World, r: Resident) -> list[str]:
    """What `r` is told of the business where it is: while it is open, what it sells and at what
    price; while it is shut, that it is, and its keeper what it sells all the same; the Store's
    keeper what is on order; and the chef, at the Store or the Restaurant, what the kitchen
    holds."""
    told = []
    c = world.config
    for business in BUSINESSES.values():
        if r.place != business.place(c).id:
            continue
        keeper = business.keeps(r.occupation.id)
        if business.serving(world) is None:
            told.append(business.closed_told(c))
            if keeper and business.kept is not None:
                told.append(business.kept + offered(world, business))
        else:
            told.append(business.selling + offered(world, business))
        if keeper and business is STORE and world.store.pending:
            coming: dict[str, int] = {}
            for item, units, _ in world.store.pending:
                add(coming, str(item), int(units))
            told.append(f"On order from the supplier: {listed(world.held_told(coming))}.")
    if KITCHEN.keeps(r.occupation.id) and r.place in (STORE.place(c).id, KITCHEN.place(c).id):
        told.append(kitchen_told(world))
    return told


def kitchen_told(world: World) -> str:
    """What the kitchen's larder holds, as the chef reads it."""
    held = world.held_told(world.holders[LARDER].items)
    return f"The kitchen holds {listed(held)}." if held else "The kitchen holds nothing."
