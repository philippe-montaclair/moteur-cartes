"""
Tests de la validation des réponses.

La première section rejoue EXACTEMENT les réponses qui étaient refusées à
tort dans la version précédente. Ce sont des tests de non-régression :
tant qu'ils passent, la panne ne peut pas revenir.
"""

import json

from conftest import carte_par_titre, fausse_carte

from database import (
    charger_liste_json,
    controler_donnees,
    lister_cartes,
    mots_significatifs,
    normaliser_code,
    normaliser_reponse,
    reponse_acceptee,
    reponses_de_la_carte,
    valider_reponse,
)


def est_correct(reponse, carte):
    return valider_reponse(reponse, carte)["correct"]


# ---------------------------------------------------------------------------
# 1. Les réponses qui étaient refusées à tort
# ---------------------------------------------------------------------------

def test_reconnaitre_les_types_sans_point_final():
    carte = carte_par_titre("Reconnaître les types")
    assert est_correct("int, float, str et bool", carte)
    assert est_correct("int, float, str et bool.", carte)
    assert est_correct("int float str bool", carte)
    assert est_correct("INT, FLOAT, STR ET BOOL", carte)


def test_repeter_avec_while_en_phrase_complete():
    carte = carte_par_titre("Répéter avec while")
    assert est_correct("while", carte)
    assert est_correct("Le mot-clé est while.", carte)
    assert est_correct("  While  ", carte)
    assert est_correct("la boucle while", carte)


def test_calculer_un_quotient():
    carte = carte_par_titre("Calculer un quotient")
    assert est_correct("/ produit un quotient décimal ; // réalise une division entière", carte)
    assert est_correct("/ donne un décimal et // donne un entier", carte)
    assert est_correct("le / renvoie un float alors que le // renvoie un entier", carte)


def test_compter_des_repetitions():
    carte = carte_par_titre("Compter des répétitions")
    assert est_correct("print est exécuté 3 fois.", carte)
    assert est_correct("3 fois", carte)
    assert est_correct("trois fois", carte)


def test_ajouter_a_une_liste_exige_la_forme_complete():
    """
    Ici on veut au contraire de la PRÉCISION : « append » seul ne décrit pas
    l'instruction demandée. La réponse doit être signalée « proche », pas
    validée — et surtout pas rejetée sèchement.
    """
    carte = carte_par_titre("Ajouter à une liste")
    assert est_correct("nombres.append(4)", carte)
    assert est_correct("nombres.append( 4 )", carte)
    assert est_correct("NOMBRES.APPEND(4)", carte)

    resultat = valider_reponse("append", carte)
    assert resultat["correct"] is False
    assert resultat["statut"] == "proche"


# ---------------------------------------------------------------------------
# 2. Normalisation
# ---------------------------------------------------------------------------

def test_normaliser_ignore_casse_accents_et_ponctuation():
    assert normaliser_reponse("  Le mot-clé est WHILE.  ") == "le mot cle est while"
    assert normaliser_reponse("Élève") == "eleve"
    assert normaliser_reponse(None) == ""


def test_normaliser_preserve_les_operateurs():
    """Sans cela, « / » et « // » disparaîtraient et la réponse serait vide."""
    assert "//" in normaliser_reponse("// division entière")
    assert "%" in normaliser_reponse("l'opérateur %")
    assert "**" in normaliser_reponse("**")
    assert normaliser_reponse("#") == "#"


def test_normaliser_code_ignore_les_espaces_et_les_guillemets():
    assert normaliser_code("print( 'a' )") == "print('a')"
    assert normaliser_code('print("a")') == "print('a')"
    assert normaliser_code("nombres.append( 4 )") == "nombres.append(4)"


def test_mots_significatifs_retire_les_mots_vides():
    assert mots_significatifs("Le mot-clé est while") == ["while"]


# ---------------------------------------------------------------------------
# 3. Robustesse des données
# ---------------------------------------------------------------------------

def test_charger_liste_json_supporte_les_cas_degrades():
    assert charger_liste_json('["a", "b"]') == ["a", "b"]
    assert charger_liste_json("[]") == []
    assert charger_liste_json(None) == []
    assert charger_liste_json("") == []
    assert charger_liste_json("null") == []
    assert charger_liste_json('"while"') == ["while"]
    # JSON invalide : on retombe sur un découpage par virgules
    assert charger_liste_json("while, tant que") == ["while", "tant que"]


def test_reponse_canonique_sert_de_filet_si_la_liste_est_vide():
    """Le cas suspecté dans l'ancienne base : reponses_acceptees == []."""
    carte = fausse_carte("while", acceptees=[])
    assert reponses_de_la_carte(carte) == ["while"]
    assert est_correct("while", carte)
    assert est_correct("Le mot-clé est while.", carte)


def test_json_corrompu_ne_fait_pas_planter_la_validation():
    carte = fausse_carte("while", acceptees=None)
    carte["reponses_acceptees"] = "{ceci n'est pas du JSON"
    assert est_correct("while", carte) is True


# ---------------------------------------------------------------------------
# 4. Pas de faux positifs
# ---------------------------------------------------------------------------

def test_une_reponse_fausse_reste_fausse():
    carte = carte_par_titre("Répéter avec while")
    assert not est_correct("for", carte)
    assert not est_correct("je ne sais pas", carte)
    assert not est_correct("", carte)
    assert not est_correct("   ", carte)


def test_int_ne_doit_pas_etre_trouve_dans_print():
    """Piège classique de la comparaison par sous-chaîne."""
    carte = fausse_carte("int", acceptees=["int"], type_="mot_cle")
    assert not est_correct("print", carte)
    assert est_correct("le type est int", carte)


def test_un_mot_cle_court_ne_matche_pas_un_mot_plus_long():
    """« in » ne doit pas valider « int » : les mots courts exigent l'exactitude."""
    carte = carte_par_titre("Tester une appartenance")
    assert est_correct("in", carte)
    assert est_correct("le mot-clé in", carte)
    assert not est_correct("int", carte)


def test_code_accepte_l_instruction_noyee_dans_une_phrase():
    carte = carte_par_titre("Longueur d'une chaîne")
    assert est_correct("len(mot)", carte)
    assert est_correct("la réponse est len(mot)", carte)
    assert est_correct("len(mot).", carte)
    assert not est_correct("count(mot)", carte)


def test_mots_cles_requis_exigent_toutes_les_notions():
    carte = fausse_carte(
        "une division décimale et une division entière",
        acceptees=[],
        mots_cles=[["decimal"], ["entier", "entiere"]],
    )
    assert est_correct("c'est décimal ou entier selon l'opérateur", carte)
    assert not est_correct("c'est décimal", carte)


# ---------------------------------------------------------------------------
# 5. Compatibilité avec l'ancienne signature
# ---------------------------------------------------------------------------

def test_reponse_acceptee_ancienne_api():
    assert reponse_acceptee("while", ["while", "le mot-clé while"]) is True
    assert reponse_acceptee("WHILE ", ["while"]) is True
    assert reponse_acceptee("for", ["while"]) is False


# ---------------------------------------------------------------------------
# 6. Intégrité du jeu de questions
# ---------------------------------------------------------------------------

def test_le_niveau_1_contient_au_moins_50_questions():
    assert len([c for c in lister_cartes() if c["niveau"] == 1]) >= 50


def test_aucune_anomalie_dans_les_donnees():
    """
    Vérifie carte par carte que la réponse attendue est bien acceptée par le
    validateur. C'est le contrôle qui manquait : une carte mal remplie était
    invisible jusqu'à ce qu'un utilisateur tombe dessus.
    """
    assert controler_donnees() == []


def test_chaque_carte_a_au_moins_une_reponse_acceptee():
    for carte in lister_cartes():
        assert reponses_de_la_carte(carte), f"Carte {carte['id']} sans réponse"


def test_chaque_carte_a_une_explication_et_un_indice():
    for carte in lister_cartes():
        assert carte["explication"].strip(), f"Carte {carte['id']} sans explication"
        assert carte["indice"].strip(), f"Carte {carte['id']} sans indice"


# ---------------------------------------------------------------------------
# Polarité — une négation inverse le sens, elle n'ajoute pas un mot
# ---------------------------------------------------------------------------
#
# Défaut trouvé le 19 août 2026 par le vérificateur de filets, au premier
# import des paquets IA et Linux. Trois chemins d'acceptation sur quatre
# validaient le contraire de la bonne réponse : ils comptent des mots
# présents, et une négation ne retire aucun mot.

def _carte(reponse, acceptees, mots_cles):
    import json
    return {"reponse": reponse, "type": "texte", "langue": "fr",
            "reponses_acceptees": json.dumps(acceptees),
            "mots_cles": json.dumps(mots_cles)}


def test_une_negation_ajoutee_n_est_pas_la_bonne_reponse():
    carte = _carte("c'est un entier", ["c'est un entier"], [["entier"]])
    assert valider_reponse("c'est un entier", carte)["correct"] is True
    assert valider_reponse("ce n'est pas un entier", carte)["correct"] is False
    assert valider_reponse("jamais un entier", carte)["correct"] is False


def test_le_contraire_d_un_terme_specialise_est_refuse():
    carte = _carte("apprentissage supervisé", ["apprentissage supervisé"],
                   [["apprentissage supervise", "supervise"]])
    assert valider_reponse("apprentissage supervisé", carte)["correct"] is True
    assert valider_reponse("apprentissage non supervisé", carte)["correct"] is False


def test_une_negation_retiree_n_est_pas_la_bonne_reponse_non_plus():
    """La garde vaut dans les deux sens : la réponse attendue peut nier."""
    carte = _carte("il ne modifie pas le modèle", ["il ne modifie pas le modèle"],
                   [["modifie"]])
    assert valider_reponse("il ne modifie pas le modèle", carte)["correct"] is True
    assert valider_reponse("il modifie le modèle", carte)["correct"] is False


def test_une_reponse_sans_negation_reste_acceptee_normalement():
    """La garde ne doit pas resserrer ce qui n'a rien à voir avec la polarité."""
    carte = _carte("une liste", ["une liste", "liste"], [["liste"]])
    assert valider_reponse("c'est une liste", carte)["correct"] is True
    assert valider_reponse("la liste", carte)["correct"] is True


# ---------------------------------------------------------------------------
# La garde des expressions courtes — sur les DEUX chemins d'acceptation
# ---------------------------------------------------------------------------
#
# Défaut trouvé le 2 septembre 2026 en écrivant `demonstration.py`, sur une
# carte réellement livrée. La garde avait été écrite le 21 août à l'intérieur
# de `_contient_expression` : elle protégeait le chemin des
# `reponses_acceptees` et pas celui des `mots_cles`, qui avait sa propre
# comparaison. Résultat : la carte attendant « str » notait CORRECT la
# réponse « int, float, str et bool » — le défaut même que la passation du
# 21 août déclarait corrigé.

def _carte_courte(reponse, mots_cles=None, acceptees=None):
    return {
        "id": 0, "type": "mot_cle", "reponse": reponse,
        "reponses_acceptees": json.dumps(acceptees or [reponse]),
        "mots_cles": json.dumps(mots_cles or []),
    }


def test_une_enumeration_n_est_pas_une_reponse_par_les_mots_cles():
    """LE test de non-régression du 02/09. Sans lui, rien ne retient la garde
    du côté `mots_cles`."""
    carte = _carte_courte("str", mots_cles=[["str"]])
    assert not valider_reponse("int, float, str et bool", carte)["correct"]


def test_une_enumeration_n_est_pas_une_reponse_par_les_acceptees():
    carte = _carte_courte("str", acceptees=["str"])
    assert not valider_reponse("int, float, str et bool", carte)["correct"]


def test_les_deux_chemins_rendent_le_meme_verdict():
    """La thèse du projet est « une seule correction ». Deux chemins qui
    divergent sur la même réponse, c'est la même faute qu'en août — la
    correction en deux exemplaires."""
    enonce = "int, float, str et bool"
    par_mots_cles = valider_reponse(enonce, _carte_courte("str",
                                                          mots_cles=[["str"]]))
    par_acceptees = valider_reponse(enonce, _carte_courte("str",
                                                          acceptees=["str"]))
    assert par_mots_cles["correct"] == par_acceptees["correct"]


def test_une_reponse_courte_et_juste_reste_acceptee():
    """Le pendant : à trop serrer la garde, on refuse du juste. « le type est
    int » compte deux mots porteurs, pas quatre."""
    carte = _carte_courte("int", mots_cles=[["int"]])
    assert valider_reponse("int", carte)["correct"]
    assert valider_reponse("le type est int", carte)["correct"]


def test_un_mot_long_n_est_pas_concerne_par_la_garde():
    """La garde ne vise que les expressions de moins de quatre caractères :
    « dictionnaire » ne se trouve pas par hasard dans une phrase."""
    carte = _carte_courte("dictionnaire", mots_cles=[["dictionnaire"]])
    assert valider_reponse(
        "un dictionnaire, une liste, un tuple et un ensemble", carte)["correct"]


def test_un_mot_de_liaison_ne_prouve_rien_par_les_mots_cles():
    carte = _carte_courte("or", mots_cles=[["or"]])
    assert not valider_reponse("une valeur truthy ou falsy", carte)["correct"]
