"""Constants for the Strava.cz integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "strava_cz"

ACCOUNT_TYPE_CANTEEN = "canteen"
ACCOUNT_TYPE_PERSONAL = "personal"

CONF_ACCOUNT_TYPE = "account_type"
CONF_ACCOUNTS = "accounts"
CONF_CANTEEN_NUMBER = "canteen_number"

DEFAULT_UPDATE_INTERVAL = timedelta(minutes=15)
API_TIMEOUT = 60.0

PERSONAL_S4_FIELDS = "VERZE,URLWSDL_S-URL,UR_OTVIRAK,IGN_CERT"

LEGACY_CHILD_KEY = "account"

PLATFORMS = [Platform.SENSOR, Platform.SELECT]
