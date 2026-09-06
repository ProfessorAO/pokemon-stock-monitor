from .base import GenericAdapter


class SmythsAdapter(GenericAdapter):
    """Smyths Toys. No special-casing yet — override discover()/check() here
    if this retailer needs different handling than the generic engine."""
