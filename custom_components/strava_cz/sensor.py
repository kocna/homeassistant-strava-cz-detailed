"""Sensors for Strava.cz."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import StravaCZCoordinator
from .detail import vegan_summary
from .entity import StravaCZEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: StravaCZCoordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    for child_key in coordinator.child_keys:
        entities.extend(
            [
                StravaCZBalanceSensor(coordinator, child_key),
                StravaCZDaySensor(
                    coordinator, child_key, 0, "Dnešní oběd", "today_lunch"
                ),
                StravaCZDaySensor(
                    coordinator, child_key, 1, "Zítřejší oběd", "tomorrow_lunch"
                ),
                StravaCZNextOrderedSensor(coordinator, child_key),
                StravaCZWeekMenuSensor(coordinator, child_key),
                StravaCZNextWeekMenuSensor(coordinator, child_key),
            ]
        )

    async_add_entities(entities)


def _day_for_offset(
    data: dict[str, Any], offset: int
) -> dict[str, Any] | None:
    wanted = (dt_util.now().date() + timedelta(days=offset)).isoformat()
    return next((day for day in data.get("days", []) if day["date"] == wanted), None)


def _main_meals(day: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not day:
        return []
    return [meal for meal in day.get("meals", []) if meal.get("type") == "main"]


class StravaCZBalanceSensor(StravaCZEntity, SensorEntity):
    """Account balance sensor."""

    _attr_name = "Zůstatek"
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator: StravaCZCoordinator, child_key: str) -> None:
        super().__init__(coordinator, child_key)
        self._attr_unique_id = self.make_unique_id("balance")

    @property
    def native_value(self) -> float | None:
        return self.child_data.get("user", {}).get("balance")

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self.child_data.get("user", {}).get("currency", "Kč")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        user = self.child_data.get("user", {})
        return {
            "jídelna": user.get("canteen_name"),
            "číslo_jídelny": user.get("canteen_number"),
            "uživatel": user.get("full_name"),
            "účet": user.get("username"),
        }


class StravaCZDaySensor(StravaCZEntity, SensorEntity):
    """Lunch summary for today or tomorrow."""

    _attr_icon = "mdi:food"

    def __init__(
        self,
        coordinator: StravaCZCoordinator,
        child_key: str,
        offset: int,
        name: str,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator, child_key)
        self._offset = offset
        self._attr_name = name
        self._attr_unique_id = self.make_unique_id(unique_suffix)

    @property
    def native_value(self) -> str:
        day = _day_for_offset(self.child_data, self._offset)
        meals = _main_meals(day)
        ordered = [meal for meal in meals if meal.get("ordered")]

        if ordered:
            return ordered[0].get("name") or "Objednáno"
        if not day:
            return "Bez jídelníčku"
        if day.get("no_school"):
            return "Nevaří se"
        return "Neobjednáno"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        day = _day_for_offset(self.child_data, self._offset)
        if not day:
            return {}

        meals = _main_meals(day)
        soup = next(
            (meal for meal in day.get("meals", []) if meal.get("type") == "soup"),
            None,
        )

        return {
            "datum": day.get("date"),
            "stav_dne": day.get("status_description"),
            "automatická_objednávka": day.get("auto_ordered"),
            "polévka": soup.get("name") if soup else None,
            "varianty": [
                {
                    "id": meal.get("id"),
                    "varianta": meal.get("variant"),
                    "název": meal.get("name"),
                    "cena": meal.get("price"),
                    "objednáno": meal.get("ordered"),
                    "lze_objednat": meal.get("can_order"),
                    "lze_zrušit": meal.get("can_cancel"),
                    "alergeny": [a.get("code") for a in meal.get("allergens", [])],
                    "uzávěrka": meal.get("deadline"),
                }
                for meal in meals
            ],
        }


class StravaCZWeekMenuSensor(StravaCZEntity, SensorEntity):
    """Current school-week menu with all meal variants."""

    _attr_name = "Týdenní jídelníček"
    _attr_icon = "mdi:calendar-week"

    def __init__(self, coordinator: StravaCZCoordinator, child_key: str) -> None:
        super().__init__(coordinator, child_key)
        self._attr_unique_id = self.make_unique_id("week_menu")

    @staticmethod
    def _bounds():
        today = dt_util.now().date()
        if today.weekday() >= 5:
            start = today + timedelta(days=7 - today.weekday())
        else:
            start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=4)

    def _week_days(self) -> list[dict[str, Any]]:
        start, end = self._bounds()
        start_iso = start.isoformat()
        end_iso = end.isoformat()
        return [
            day
            for day in self.child_data.get("days", [])
            if start_iso <= day.get("date", "") <= end_iso
        ]

    def _vegan_fields(self, day: dict[str, Any], meal: dict[str, Any]) -> dict[str, Any]:
        """Rozbor veganství z detailu jídla (jen u hlavních jídel, pokud ho máme)."""
        if meal.get("type") != "main":
            return {}
        detail = self.coordinator.detail_for(
            self.child_key, meal.get("date"), meal.get("variant"), meal.get("name")
        )
        if not detail or not detail.get("courses"):
            return {}
        soup = next((m for m in day.get("meals", []) if m.get("type") == "soup"), None)
        soup_codes = [a.get("code") for a in soup.get("allergens", [])] if soup else []
        summary = vegan_summary(detail, soup_allergens=soup_codes)
        return {"vegan": summary["ok"], "rozbor": summary["label"]}

    @property
    def native_value(self) -> str:
        start, end = self._bounds()
        return f"{start:%d.%m.}–{end:%d.%m.}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        start, end = self._bounds()
        days: list[dict[str, Any]] = []

        for day in self._week_days():
            meals = []
            for meal in day.get("meals", []):
                meals.append(
                    {
                        "id": meal.get("id"),
                        "typ": meal.get("type"),
                        "varianta": meal.get("variant"),
                        "název": meal.get("name"),
                        "cena": meal.get("price"),
                        "objednáno": meal.get("ordered"),
                        "lze_objednat": meal.get("can_order"),
                        "lze_zrušit": meal.get("can_cancel"),
                        "alergeny": [
                            allergen.get("code")
                            for allergen in meal.get("allergens", [])
                        ],
                        "uzávěrka": meal.get("deadline"),
                        **self._vegan_fields(day, meal),
                    }
                )

            days.append(
                {
                    "datum": day.get("date"),
                    "stav": day.get("status_description"),
                    "nevaří_se": day.get("no_school"),
                    "jídla": meals,
                }
            )

        return {
            "od": start.isoformat(),
            "do": end.isoformat(),
            "dny": days,
        }


class StravaCZNextWeekMenuSensor(StravaCZWeekMenuSensor):
    """Menu of the following school week (always the week after the current one)."""

    _attr_name = "Jídelníček příští týden"

    def __init__(self, coordinator: StravaCZCoordinator, child_key: str) -> None:
        super().__init__(coordinator, child_key)
        self._attr_unique_id = self.make_unique_id("next_week_menu")

    @staticmethod
    def _bounds():
        today = dt_util.now().date()
        if today.weekday() >= 5:
            base = today + timedelta(days=7 - today.weekday())
        else:
            base = today - timedelta(days=today.weekday())
        start = base + timedelta(days=7)
        return start, start + timedelta(days=4)


class StravaCZNextOrderedSensor(StravaCZEntity, SensorEntity):
    """Next ordered main meal."""

    _attr_name = "Příští objednaný oběd"
    _attr_icon = "mdi:calendar-check"

    def __init__(self, coordinator: StravaCZCoordinator, child_key: str) -> None:
        super().__init__(coordinator, child_key)
        self._attr_unique_id = self.make_unique_id("next_ordered")

    def _next(self) -> dict[str, Any] | None:
        today = dt_util.now().date().isoformat()
        for day in self.child_data.get("days", []):
            if day.get("date", "") < today:
                continue
            for meal in day.get("meals", []):
                if meal.get("type") == "main" and meal.get("ordered"):
                    return meal
        return None

    @property
    def native_value(self) -> str:
        meal = self._next()
        return meal.get("name") if meal else "Nic objednáno"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        meal = self._next()
        if not meal:
            return {}
        return {
            "datum": meal.get("date"),
            "id": meal.get("id"),
            "varianta": meal.get("variant"),
            "cena": meal.get("price"),
        }
