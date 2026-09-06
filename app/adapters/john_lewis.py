from .base import GenericAdapter


class JohnLewisAdapter(GenericAdapter):
    """John Lewis. No special-casing yet — override discover()/check() here
    if this retailer needs different handling than the generic engine."""
