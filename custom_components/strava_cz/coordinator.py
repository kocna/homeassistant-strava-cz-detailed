"""Data coordinator for Strava.cz."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from strava_cz import AuthenticationError, StravaCZ, StravaError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ACCOUNT_TYPE_CANTEEN,
    ACCOUNT_TYPE_PERSONAL,
    API_TIMEOUT,
    CONF_ACCOUNT_TYPE,
    CONF_ACCOUNTS,
    CONF_CANTEEN_NUMBER,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    LEGACY_CHILD_KEY,
)
from .detail import BLOCKING, build_payload, parse_detail
from .personal import (
    PersonalCanteenAccount,
    canteen_login,
    canteen_properties,
    canteen_s5url,
    personal_login,
)

_LOGGER = logging.getLogger(__name__)

# Rozbor jídla po chodech a surovinách (Strava.cz orderModalDetails).
# Načítá se jen pro hlavní jídla s alergenem 03/04/07 na nejbližších pár týdnů.
DETAIL_SKIP_NAMES: tuple[str, ...] = ()   # jména dětí, pro které se rozbor nenačítá (volitelné)
DETAIL_DAYS_AHEAD = 21
DETAIL_MAX_PER_REFRESH = 25


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


class StravaCZCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate one legacy account or one personal account with linked children."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}:{entry.entry_id}",
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self.entry = entry
        self.account_type = entry.data.get(CONF_ACCOUNT_TYPE, ACCOUNT_TYPE_CANTEEN)
        self._io_lock = asyncio.Lock()
        self.last_success = None
        self.last_error: str | None = None

        self._legacy_client: StravaCZ | None = None

        self._personal_client: StravaCZ | None = None
        self._personal_sid: str | None = None
        self._personal_children: dict[str, StravaCZ] = {}
        self._s5url_cache: dict[str, str] = {}
        self._detail_cache: dict[tuple, dict[str, Any]] = {}

        self._accounts = [
            PersonalCanteenAccount.from_dict(item)
            for item in entry.data.get(CONF_ACCOUNTS, [])
            if isinstance(item, Mapping)
        ]

    @property
    def child_keys(self) -> list[str]:
        """Return stable child/device keys for this entry."""
        if self.account_type == ACCOUNT_TYPE_PERSONAL:
            return [account.key for account in self._accounts]
        return [LEGACY_CHILD_KEY]

    @property
    def is_legacy_single(self) -> bool:
        """Whether this is a pre-personal single canteen account."""
        return self.account_type != ACCOUNT_TYPE_PERSONAL

    def child_data(self, child_key: str) -> dict[str, Any]:
        """Return coordinator data for one child/account."""
        return self.data.get("children", {}).get(child_key, {})

    # --------------------------------------------------------------- classic login

    def _new_legacy_client(self) -> StravaCZ:
        return StravaCZ(
            self.entry.data[CONF_USERNAME],
            self.entry.data[CONF_PASSWORD],
            self.entry.data[CONF_CANTEEN_NUMBER],
            language="CZ",
            timeout=API_TIMEOUT,
        )

    def _ensure_legacy_client(self) -> StravaCZ:
        if self._legacy_client is None:
            self._legacy_client = self._new_legacy_client()
        return self._legacy_client

    def _close_legacy_client(self) -> None:
        if self._legacy_client is None:
            return
        with contextlib.suppress(StravaError):
            if self._legacy_client.user.is_logged_in:
                self._legacy_client.logout()
        self._legacy_client.close()
        self._legacy_client = None

    # -------------------------------------------------------------- personal login

    def _new_personal_client(self) -> StravaCZ:
        return StravaCZ(language="CZ", timeout=API_TIMEOUT)

    def _login_personal(self) -> None:
        self._close_personal_client()
        client = self._new_personal_client()
        try:
            sid = personal_login(
                client,
                self.entry.data[CONF_EMAIL],
                self.entry.data[CONF_PASSWORD],
            )
        except Exception:
            client.close()
            raise

        self._personal_client = client
        self._personal_sid = sid

    def _ensure_personal_client(self) -> tuple[StravaCZ, str]:
        if self._personal_client is None or self._personal_sid is None:
            self._login_personal()
        assert self._personal_client is not None
        assert self._personal_sid is not None
        return self._personal_client, self._personal_sid

    def _close_personal_client(self) -> None:
        self._personal_children.clear()
        self._personal_sid = None
        if self._personal_client is not None:
            self._personal_client.close()
            self._personal_client = None

    def _activate_personal_child(self, account: PersonalCanteenAccount) -> StravaCZ:
        """Switch the personal session to a child and populate an upstream client."""
        parent, personal_sid = self._ensure_personal_client()

        canteen_sid = canteen_login(parent, personal_sid, account)
        s5url = self._s5url_cache.get(account.canteen_number)
        if not s5url:
            s5url = canteen_s5url(parent, account.canteen_number)
            self._s5url_cache[account.canteen_number] = s5url

        props = canteen_properties(parent, account, canteen_sid, s5url)

        child = self._personal_children.get(account.key)
        if child is None:
            # Keep the browser-like cookies/session owned by the personal client.
            child = StravaCZ(
                language="CZ",
                client=parent._client,  # noqa: SLF001 - upstream has no public PA API
            )
            # The shared personal session is already primed; another login-page GET
            # could overwrite browser-context cookies after canteenLoginPA.
            child._session_primed = True  # noqa: SLF001
            self._personal_children[account.key] = child

        user = child.user
        user.username = account.account_id
        user.canteen_number = account.canteen_number
        user.sid = canteen_sid
        user.s5url = s5url
        user.full_name = str(props.get("jmeno") or account.account_id)
        user.email = str(props.get("email") or "") or None
        user.id = str(props.get("id") or account.account_id)
        user.currency = str(props.get("mena") or "Kč")
        user.canteen_name = str(props.get("nazevJidelny") or "") or None
        user.balance = _to_float(props.get("konto"), user.balance)
        user.is_logged_in = True
        return child

    def _activate_personal_child_with_retry(
        self, account: PersonalCanteenAccount
    ) -> StravaCZ:
        for attempt in range(2):
            try:
                return self._activate_personal_child(account)
            except AuthenticationError:
                self._close_personal_client()
                if attempt:
                    raise
        raise AuthenticationError("Přihlášení osobního účtu selhalo")

    # --------------------------------------------------------------------- data

    @staticmethod
    def _snapshot(client: StravaCZ) -> dict[str, Any]:
        user = client.user
        days: list[dict[str, Any]] = []

        for day in client.menu.days:
            meals: list[dict[str, Any]] = []
            for meal in day.meals:
                meals.append(
                    {
                        "id": meal.id,
                        "date": meal.date.isoformat(),
                        "type": meal.type.value,
                        "variant": meal.variant,
                        "name": meal.name,
                        "price": meal.price,
                        "ordered": meal.ordered,
                        "can_order": meal.can_order,
                        "can_cancel": meal.can_cancel,
                        "order_restriction": meal.order_restriction.description,
                        "cancel_restriction": meal.cancel_restriction.description,
                        "allergens": [
                            {"code": allergen.code, "name": allergen.name}
                            for allergen in meal.allergens
                        ],
                        "deadline": (
                            meal.deadline.isoformat() if meal.deadline is not None else None
                        ),
                        "druh": meal.raw.get("druh"),
                        "menu_no": meal.raw.get("cislojidelnicku")
                        or meal.raw.get("cisloJidelnicku")
                        or "1",
                    }
                )

            days.append(
                {
                    "date": day.date.isoformat(),
                    "status": day.status.value,
                    "status_description": day.status.description,
                    "auto_ordered": day.auto_ordered,
                    "ordered": day.ordered,
                    "no_school": day.no_school,
                    "meals": meals,
                }
            )

        return {
            "user": {
                "username": user.username,
                "full_name": user.full_name,
                "email": user.email,
                "balance": user.balance,
                "currency": user.currency,
                "canteen_number": user.canteen_number,
                "canteen_name": user.canteen_name,
                "account_id": user.id,
            },
            "days": days,
        }

    def _enrich_details(
        self, child_key: str, client: StravaCZ, snapshot: dict[str, Any]
    ) -> None:
        """Doplní do cache rozbor jídel (chody a suroviny). Nikdy nevyhodí chybu."""
        try:
            full_name = str(snapshot.get("user", {}).get("full_name") or "").lower()
            if any(n in full_name or n in str(child_key).lower() for n in DETAIL_SKIP_NAMES):
                return
            today = date.today().isoformat()
            limit = (date.today() + timedelta(days=DETAIL_DAYS_AHEAD)).isoformat()
            self._detail_cache = {
                k: v for k, v in self._detail_cache.items() if k[1] >= today
            }
            fetched = 0
            for day in snapshot.get("days", []):
                if day["date"] < today or day["date"] > limit or day.get("no_school"):
                    continue
                for meal in day.get("meals", []):
                    if meal.get("type") != "main":
                        continue
                    codes = {a["code"] for a in meal.get("allergens", [])}
                    if not codes & set(BLOCKING):
                        continue
                    key = (child_key, meal["date"], meal["variant"], meal["name"])
                    if key in self._detail_cache:
                        continue
                    if fetched >= DETAIL_MAX_PER_REFRESH:
                        return
                    fetched += 1
                    try:
                        response = client._request(  # noqa: SLF001
                            "orderModalDetails",
                            build_payload(
                                client.user,
                                "CZ",
                                meal["id"],
                                meal["date"],
                                meal.get("druh") or "",
                                meal.get("menu_no") or "1",
                            ),
                            authenticated=True,
                        )
                        self._detail_cache[key] = parse_detail(response)
                    except StravaError as err:
                        _LOGGER.debug("Detail jídla %s se nepodařilo načíst: %s", key, err)
        except Exception:  # noqa: BLE001 - rozbor je doplněk, nesmí rozbít aktualizaci
            _LOGGER.debug("Načtení rozboru jídel selhalo", exc_info=True)

    def detail_for(
        self, child_key: str, day: str, variant: str, name: str
    ) -> dict[str, Any] | None:
        """Rozbor jídla z cache, nebo None, pokud ho nemáme."""
        return self._detail_cache.get((child_key, day, variant, name))

    def _fetch_legacy(self) -> dict[str, Any]:
        client = self._ensure_legacy_client()
        try:
            client.menu.fetch()
        except AuthenticationError:
            self._close_legacy_client()
            client = self._ensure_legacy_client()
            client.menu.fetch()

        snapshot = self._snapshot(client)
        self._enrich_details(LEGACY_CHILD_KEY, client, snapshot)
        return {"children": {LEGACY_CHILD_KEY: snapshot}}

    def _fetch_personal(self) -> dict[str, Any]:
        children: dict[str, Any] = {}
        for account in self._accounts:
            child = self._activate_personal_child_with_retry(account)
            child.menu.fetch()
            snapshot = self._snapshot(child)
            self._enrich_details(account.key, child, snapshot)
            children[account.key] = snapshot
        return {"children": children}

    def _fetch_sync(self) -> dict[str, Any]:
        if self.account_type == ACCOUNT_TYPE_PERSONAL:
            return self._fetch_personal()
        return self._fetch_legacy()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data; on any failure keep the last known data and remember the error."""
        async with self._io_lock:
            try:
                data = await self.hass.async_add_executor_job(self._fetch_sync)
            except AuthenticationError as err:
                self.last_error = f"přihlášení selhalo: {err}"
                if self.data:
                    _LOGGER.warning("Strava.cz: %s, ponechávám poslední známá data", self.last_error)
                    self.entry.async_start_reauth(self.hass)
                    return self.data
                raise ConfigEntryAuthFailed("Strava.cz authentication failed") from err
            except Exception as err:  # noqa: BLE001 - jakékoli selhání nesmí smazat data
                self.last_error = str(err)
                if self.data:
                    _LOGGER.warning("Strava.cz: obnovení selhalo (%s), ponechávám poslední známá data", err)
                    return self.data
                raise UpdateFailed(f"Strava.cz update failed: {err}") from err
            self.last_success = dt_util.now()
            self.last_error = None
            return data

    # ------------------------------------------------------------------- actions

    def _change_legacy_meal(self, meal_id: int, ordered: bool) -> dict[str, Any]:
        for attempt in range(2):
            client = self._ensure_legacy_client()
            try:
                client.menu.fetch()
                if ordered:
                    client.menu.order_meals(meal_id)
                else:
                    client.menu.cancel_meals(meal_id)
                return self._snapshot(client)
            except AuthenticationError:
                self._close_legacy_client()
                if attempt:
                    raise
        raise AuthenticationError("Strava.cz authentication failed")

    def _account_by_key(self, child_key: str) -> PersonalCanteenAccount:
        for account in self._accounts:
            if account.key == child_key:
                return account
        raise StravaError(f"Unknown Strava.cz account {child_key!r}")

    def _change_personal_meal(
        self, child_key: str, meal_id: int, ordered: bool
    ) -> dict[str, Any]:
        account = self._account_by_key(child_key)
        child = self._activate_personal_child_with_retry(account)
        child.menu.fetch()

        if ordered:
            child.menu.order_meals(meal_id)
        else:
            child.menu.cancel_meals(meal_id)

        return self._snapshot(child)

    async def async_change_meal(
        self, child_key: str, meal_id: int, ordered: bool
    ) -> None:
        """Order or cancel a meal and publish the updated child data."""
        async with self._io_lock:
            try:
                if self.account_type == ACCOUNT_TYPE_PERSONAL:
                    child_data = await self.hass.async_add_executor_job(
                        self._change_personal_meal,
                        child_key,
                        int(meal_id),
                        ordered,
                    )
                else:
                    child_data = await self.hass.async_add_executor_job(
                        self._change_legacy_meal,
                        int(meal_id),
                        ordered,
                    )
            except AuthenticationError as err:
                raise ConfigEntryAuthFailed("Strava.cz authentication failed") from err
            except StravaError as err:
                raise HomeAssistantError(str(err)) from err

            current = dict(self.data or {})
            children = dict(current.get("children", {}))
            children[child_key] = child_data
            current["children"] = children
            self.async_set_updated_data(current)

    async def async_close(self) -> None:
        """Close HTTP sessions."""
        async with self._io_lock:
            await self.hass.async_add_executor_job(self._close_legacy_client)
            await self.hass.async_add_executor_job(self._close_personal_client)
