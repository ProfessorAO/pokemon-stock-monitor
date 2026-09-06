from .base import GenericAdapter


class MagicMadhouseAdapter(GenericAdapter):
    """Magic Madhouse. No special-casing yet — override discover()/check() here
    if this retailer needs different handling than the generic engine."""
