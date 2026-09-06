from .base import GenericAdapter


class PokemonCenterAdapter(GenericAdapter):
    """Pokémon Center. No special-casing yet — override discover()/check() here
    if this retailer needs different handling than the generic engine."""
