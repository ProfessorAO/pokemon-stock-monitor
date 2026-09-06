from .base import GenericAdapter


class AuroraSparksAdapter(GenericAdapter):
    """Aurora Sparks. No special-casing yet — override discover()/check() here
    if this retailer needs different handling than the generic engine."""
