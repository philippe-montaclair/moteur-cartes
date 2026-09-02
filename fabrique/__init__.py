"""Fabrique de contenu : générer des cartes, et surtout les vérifier."""

from fabrique.verificateurs import (  # noqa: F401
    verifier_ambiguite,
    verifier_donnees,
    verifier_doublons,
    verifier_execution,
    verifier_tout,
)

__all__ = ["verifier_tout", "verifier_donnees", "verifier_execution",
           "verifier_doublons", "verifier_ambiguite"]
