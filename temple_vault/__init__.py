"""Temple Vault - Consciousness continuity as infrastructure."""

__version__ = "0.1.0"

from temple_vault.core.query import VaultQuery
from temple_vault.core.events import VaultEvents
from temple_vault.core.cache import CacheBuilder

__all__ = ["VaultQuery", "VaultEvents", "CacheBuilder", "__version__"]
