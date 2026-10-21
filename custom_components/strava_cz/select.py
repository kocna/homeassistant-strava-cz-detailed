"""Action selects for ordering and cancelling Strava.cz lunches."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import StravaCZCoordinator
from .entity import StravaCZEntity

PLACEHOLDER_OPTION = "— Vyberte oběd —"

# "main" = hlavní jídlo (Oběd 1 / Oběd 2 / Oběd MŠ).
# "unknown" = přesnídávka a svačina ve školce (mají vlastní id a typ "unknown").
# Polévky ("soup") se neobjednávají samostatně.
ORDERABLE_TYPES = ("main", "unknown")


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: StravaCZCoordinator = entry.runtime_data
    entities: list[SelectEntity] = []

    for child_key in coordinator.child_keys:
        entities.extend(
            [
                StravaCZMealActionSelect(coordinator, child_key, order=True),
                StravaCZMealActionSelect(coordinator, child_key, order=False),
            ]
        )

    async_add_entities(entities)


def _option_label(meal: dict[str, Any]) -> str:
    raw = (
        f"{meal['date'][8:10]}.{meal['date'][5:7]}. | "
        f"{meal.get('variant') or 'Oběd'} | {meal.get('name') or ''} (#{meal['id']})"
    )
    return raw[:250]


class StravaCZMealActionSelect(StravaCZEntity, SelectEntity):
    """Select a meal to order or cancel."""

    _attr_icon = "mdi:food-variant"

    def __init__(
        self,
        coordinator: StravaCZCoordinator,
        child_key: str,
        *,
        order: bool,
    ) -> None:
        super().__init__(coordinator, child_key)
        self._order = order
        self._attr_name = "Objednat oběd" if order else "Zrušit oběd"
        suffix = "order_lunch" if order else "cancel_lunch"
        self._attr_unique_id = self.make_unique_id(suffix)

    def _meal_map(self) -> dict[str, int]:
        today = dt_util.now().date().isoformat()
        result: dict[str, int] = {}

        for day in self.child_data.get("days", []):
            if day.get("date", "") < today:
                continue
            for meal in day.get("meals", []):
                if meal.get("type") not in ORDERABLE_TYPES:
                    continue

                if self._order:
                    eligible = bool(meal.get("can_order")) and not bool(
                        meal.get("ordered")
                    )
                else:
                    eligible = bool(meal.get("ordered")) and bool(
                        meal.get("can_cancel")
                    )

                if eligible:
                    result[_option_label(meal)] = int(meal["id"])
        return result

    @property
    def options(self) -> list[str]:
        return [PLACEHOLDER_OPTION, *self._meal_map().keys()]

    @property
    def current_option(self) -> str:
        return PLACEHOLDER_OPTION

    async def async_select_option(self, option: str) -> None:
        if option == PLACEHOLDER_OPTION:
            return

        meal_id = self._meal_map().get(option)
        if meal_id is None:
            raise HomeAssistantError(
                "Vybrané jídlo už není dostupné. Obnov data integrace a zkus to znovu."
            )
        await self.coordinator.async_change_meal(
            self.child_key,
            meal_id,
            ordered=self._order,
        )
