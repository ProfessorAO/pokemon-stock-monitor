from .base import GenericAdapter


class GameAdapter(GenericAdapter):
    """GAME. No special-casing yet — override discover()/check() here
    if this retailer needs different handling than the generic engine."""
