from .base import GenericAdapter


class EternaCardsAdapter(GenericAdapter):
    """Eterna Cards. No special-casing yet — override discover()/check() here
    if this retailer needs different handling than the generic engine."""
