from .base import GenericAdapter


class TheCardVaultAdapter(GenericAdapter):
    """The Card Vault. No special-casing yet — override discover()/check() here
    if this retailer needs different handling than the generic engine."""
