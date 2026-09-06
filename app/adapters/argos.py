from .base import GenericAdapter


class ArgosAdapter(GenericAdapter):
    """Argos. No special-casing yet — override discover()/check() here
    if this retailer needs different handling than the generic engine."""
