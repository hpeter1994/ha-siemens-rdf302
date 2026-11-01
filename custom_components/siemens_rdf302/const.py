"""Constants for the Siemens RDF302 integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "siemens_rdf302"
MANUFACTURER: Final = "Siemens"

CONF_APPLICATION: Final = "application"
CONF_MODEL: Final = "model"
CONF_UNIT_ID: Final = "unit_id"

DEFAULT_PORT: Final = 502
DEFAULT_UNIT_ID: Final = 1
DEFAULT_NAME: Final = "RDF302"

FAST_SCAN_INTERVAL: Final = timedelta(seconds=30)
SLOW_SCAN_INTERVAL: Final = timedelta(hours=1)

# Keeps the RS485 side of the bridge quiet between requests.
MESSAGE_SPACING: Final = 0.05
