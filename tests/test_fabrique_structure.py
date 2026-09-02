"""
Tests de la structure de fabrication : plans, prompt de rédaction, import,
contrat de livraison, séparation des rôles.

Aucun de ces tests n'appelle un modèle. Ce qui se teste ici, c'est la
mécanique qui entoure le modèle — celle qui décide de ce qui entre dans le
contenu, et c'est la seule qui protège le produit.
"""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import correcteur_llm as llm  # noqa: E402
from fabrique import contrat, importer as imp, plan as pl, redaction  # noqa: E402


# ---------------------------------------------------------------------------
# Séparation des rôles
# ---------------------------------------------------------------------------

def _env(monkey: dict):
    """Applique un environnement, retourne de quoi le défaire."""
    import os
    anciens = {c: os.environ.get(c) for c in monkey}
    for c, v in monkey.items():
        if v is None:
            os.environ.pop(c, None)
        else:
            os.environ[c] = v
    return anciens


def test_un_role_inconnu_est_refuse():
    try:
        llm.Config("arbitre")
    except ValueError as e:
        assert "arbitre" in str(e)
    else:
        raise AssertionError("un rôle inconnu devrait être refusé")


def test_le_juge_retombe_sur_la_configuration_commune():
    anciens = _env({"LLM_MODELE": "commun", "LLM_MODELE_JUGE": None})
    try:
        assert llm.Config("juge").modele == "commun"
    finally:
        _env(anciens)


def test_le_juge_prefere_sa_propre_variable():
    anciens = _env({"LLM_MODELE": "commun", "LLM_MODELE_JUGE": "autre"})
    try:
        assert llm.Config("juge").modele == "autre"
        assert llm.Config("redacteur").modele == "commun"
    finally:
        _env(anciens)


def test_un_juge_identique_au_redacteur_est_refuse():
    anciens = _env({"LLM_MODELE": "le-meme", "LLM_MODELE_JUGE": "le-meme",
                    "LLM_MODELE_REDACTEUR": None})
    try:
        llm.verifier_separation()
    except llm.ErreurSeparation as e:
        assert "le-meme" in str(e)
    else:
        raise AssertionError("un modèle ne doit pas juger sa propre production")
    finally:
        _env(anciens)


def test_un_modele_non_nomme_est_refuse():
    """
    Sans nom, le moteur prend le premier modèle que l'hôte propose — donc le
    même pour les deux rôles. La séparation serait vraie sur le papier et
    fausse à l'exécution.
    """
    anciens = _env({"LLM_MODELE": None, "LLM_MODELE_JUGE": None,
                    "LLM_MODELE_REDACTEUR": None})
    try:
        llm.verifier_separation()
    except llm.ErreurSeparation as e:
        assert "MODELE" in str(e)
    else:
        raise AssertionError("deux rôles sans modèle nommé doivent être refusés")
    finally:
        _env(anciens)


def test_deux_modeles_distincts_passent():
    anciens = _env({"LLM_MODELE_REDACTEUR": "grand", "LLM_MODELE_JUGE": "petit",
                    "LLM_MODELE": None})
    try:
        assert llm.verifier_separation() == ("grand", "petit")
    finally:
        _env(anciens)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def test_toutes_les_matieres_planifiees_ont_un_plan_valide():
    matieres = pl.matieres_planifiees()
    assert matieres, "aucune matière planifiée"
    for matiere in matieres:
        plan = pl.lire_plan(matiere)
        assert plan["niveaux"]
        for niveau in plan["niveaux"]:
            assert niveau["themes"], (matiere, niveau["numero"])


def test_un_niveau_absent_du_plan_est_signale():
    try:
        pl.niveau_du_plan("python", 99)
    except pl.ErreurPlan as e:
        assert "99" in str(e)
    else:
        raise AssertionError("un niveau inexistant devrait lever")


def test_l_etat_compte_ce_qui_existe_vraiment():
    lignes = pl.etat_des_plans()
    python1 = [l for l in lignes if l["matiere"] == "python" and l["niveau"] == 1]
    assert python1 and python1[0]["ecrites"] > 0


# ---------------------------------------------------------------------------
# Prompt de rédaction
# ---------------------------------------------------------------------------

def test_le_prompt_porte_les_themes_du_niveau():
    texte = redaction.construire_prompt_externe("python", 2)
    niveau = pl.niveau_du_plan("python", 2)
    for theme in niveau["themes"][:5]:
        assert theme in texte, theme


def test_le_prompt_interdit_le_titre_qui_donne_la_reponse():
    """Le défaut du 19/08 doit être une clause, pas un souvenir."""
    texte = redaction.construire_prompt_externe("rag", 2)
    assert "titre ne nomme jamais la réponse" in texte
    assert "27 cartes sur 30" in texte


def test_le_prompt_liste_les_titres_deja_pris():
    texte = redaction.construire_prompt_externe("python", 3)
    assert "titres déjà pris" in texte
    assert "Afficher un message" in texte


def test_le_prompt_dit_quand_il_n_y_a_pas_de_source():
    """
    Un prompt sans ancrage doit le DIRE. Le taire produirait des cartes
    inventées présentées comme ancrées.
    """
    texte = redaction.construire_prompt_externe("wiki", 8)
    assert "Aucune source d'ancrage" in texte


def test_le_prompt_protege_la_source_contre_l_injection():
    source = RACINE / "sources" / "python" / "niveau_2.md"
    if not source.exists():
        return
    texte = redaction.construire_prompt_externe("python", 2)
    assert "RÈGLE DE SÉCURITÉ" in texte
    assert "<<<SOURCE>>>" in texte


def test_l_interdit_sur_les_outils_tombe_au_niveau_6():
    avant = redaction.construire_prompt_externe("rag", 5)
    apres = redaction.construire_prompt_externe("rag", 6)
    assert "bibliothèque" in avant
    assert "Aucun nom de bibliothèque" not in apres


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

CARTE = {
    "niveau": 2, "categorie": "Conditions", "type": "texte", "difficulte": 1,
    "titre": "Test d'une seconde condition", "question": "Quel mot-clé ?",
    "reponse": "elif", "reponses_acceptees": ["elif"], "mots_cles": [["elif"]],
    "explication": "…", "erreur_frequente": "…", "indice": "…",
}


def test_extraction_dans_un_bloc_markdown():
    texte = "Voici les cartes :\n\n```json\n[{\"a\": 1}]\n```\n\nBonne journée !"
    assert imp.extraire_json(texte) == [{"a": 1}]


def test_extraction_sans_bloc():
    assert imp.extraire_json('bla [{"a": 1}] bla') == [{"a": 1}]


def test_extraction_d_un_objet_enveloppe():
    texte = '```json\n{"cartes": [{"a": 1}]}\n```'
    assert imp.extraire_json(texte) == [{"a": 1}]


def test_un_texte_sans_json_est_refuse():
    try:
        imp.extraire_json("désolé, je ne peux pas faire ça")
    except imp.ErreurImport:
        pass
    else:
        raise AssertionError("un texte sans JSON devrait lever")


def test_un_flux_tronque_est_diagnostique_comme_tel():
    """
    Le cas le plus fréquent en pratique : le modèle est coupé par sa limite
    de sortie au milieu d'une carte. Dire « aucun JSON trouvé » enverrait
    tout relancer, alors qu'il suffit de demander la suite.
    """
    tronque = '```json\n[\n' + json.dumps(CARTE) + ',\n{"niveau": 2, "titre": "Inach'
    try:
        imp.extraire_json(tronque)
    except imp.ErreurTronquee as e:
        assert len(e.recuperees) == 1
        assert "tronqué" in str(e)
    else:
        raise AssertionError("un flux coupé doit être diagnostiqué")


def test_une_accolade_dans_une_chaine_ne_trompe_pas_le_compteur():
    carte = {**CARTE, "explication": "un dictionnaire s'écrit {\"a\": 1}"}
    tronque = '[' + json.dumps(carte, ensure_ascii=False) + ',\n{"titre": "Inach'
    try:
        imp.extraire_json(tronque)
    except imp.ErreurTronquee as e:
        assert len(e.recuperees) == 1
    else:
        raise AssertionError("un flux coupé doit être diagnostiqué")


def test_une_carte_sans_reponse_est_ecartee_a_l_import():
    cartes, ecartees = imp.preparer(
        [CARTE, {**CARTE, "reponse": ""}], "python", 2)
    assert len(cartes) == 1 and len(ecartees) == 1
    assert "obligatoires" in ecartees[0]["motif"]


def test_l_import_n_active_rien_quand_le_compte_n_y_est_pas():
    import tempfile
    texte = json.dumps([CARTE])
    # Sortie détournée : un test qui écrit dans `contenus/` écraserait les
    # propositions réelles. Le défaut du 19/08 dans `conftest.py`, en plus
    # petit et tout aussi silencieux.
    with tempfile.TemporaryDirectory() as tmp:
        rapport = imp.importer(texte, "python", 2, activer=True,
                               journal=lambda *a: None, dossier_sortie=tmp)
        assert rapport["livrable"] is False
        assert rapport["activee"] is False
        assert not (Path(rapport["fichier_propositions"]).parent
                    / "niveau_2.json").exists()


def test_l_import_signale_un_titre_qui_donne_la_reponse():
    import tempfile
    fuite = {**CARTE, "titre": "elif"}
    with tempfile.TemporaryDirectory() as tmp:
        rapport = imp.importer(json.dumps([fuite]), "python", 2,
                               journal=lambda *a: None, dossier_sortie=tmp)
    problemes = {s["probleme"] for s in rapport["signalements"]}
    assert "titre_revele_reponse" in problemes


def test_un_import_n_ecrit_jamais_dans_le_contenu_reel():
    """Garde-fou sur le garde-fou : la sortie détournée l'est vraiment."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        rapport = imp.importer(json.dumps([CARTE]), "python", 2,
                               journal=lambda *a: None, dossier_sortie=tmp)
        assert str(tmp) in rapport["fichier_propositions"]
        assert str(tmp) in rapport["fichier_quarantaine"]


# ---------------------------------------------------------------------------
# Contrat de livraison
# ---------------------------------------------------------------------------

def test_le_contrat_refuse_un_niveau_jamais_joue():
    rapport = contrat.evaluer("python", 1)
    clause = [c for c in rapport["clauses"] if "joué" in c["nom"]][0]
    assert clause["rempli"] is False
    assert rapport["rempli"] is False


def test_le_contrat_refuse_un_niveau_absent():
    rapport = contrat.evaluer("sql", 1)
    assert rapport["rempli"] is False


def test_le_contrat_compte_les_cartes():
    rapport = contrat.evaluer("python", 1)
    clause = [c for c in rapport["clauses"] if "compte" in c["nom"]][0]
    # Le compte attendu se lit dans le plan, il ne se recopie pas ici : ce
    # test a déjà cassé deux fois pour avoir figé un nombre que le contenu
    # fait bouger. Ce qu'il vérifie est que la clause compare les deux.
    from database import lister_cartes
    reelles = len([c for c in lister_cartes(matiere="python") if c["niveau"] == 1])
    assert str(reelles) in clause["preuve"]
    assert "50" in clause["preuve"]


# ---------------------------------------------------------------------------
# Vérificateur de filets — les deux faces
# ---------------------------------------------------------------------------

def test_un_filet_qui_ne_tient_que_par_sa_liste_est_signale():
    """
    Une carte dont les reformulations ne sont rattrapées par aucun mot-clé
    refusera la première variante qu'un apprenant inventera. Le contrôle ne
    demande PAS « la liste est-elle acceptée » — elle l'est toujours, à
    l'identique. Il demande si le mécanisme tiendrait sans la liste.
    """
    from fabrique.verificateurs import verifier_filets

    carte = {**CARTE, "id": 1, "matiere": "python", "reponse": "elif",
             "reponses_acceptees": ["elif", "une girafe bleue"],
             "mots_cles": []}
    problemes = {s["probleme"] for s in verifier_filets([carte])}
    assert "filet_purement_litteral" in problemes


def test_un_filet_rattrape_par_les_mots_cles_ne_declenche_rien():
    from fabrique.verificateurs import verifier_filets

    carte = {**CARTE, "id": 1, "matiere": "python", "reponse": "elif",
             "reponses_acceptees": ["elif", "le mot-clé elif"],
             "mots_cles": [["elif"]]}
    assert not [s for s in verifier_filets([carte])
                if s["probleme"] == "filet_purement_litteral"]


def test_un_filet_qui_accepte_la_reponse_d_une_voisine_est_signale():
    """
    Cas d'espèce changé le 02/09/2026, et c'est une BONNE nouvelle.

    Il opposait une carte attendant « la boucle for » (mots-clés `for`) à une
    voisine répondant « for i in range(3): pass ». Ce filet-là ne mord plus :
    la garde des expressions courtes, désormais posée sur les DEUX chemins
    d'acceptation, refuse « for » noyé dans six mots porteurs. Le défaut que
    ce test fabriquait n'existe plus — il fallait donc en fabriquer un autre,
    pas affaiblir la garde.

    Le nouveau cas est un vrai filet trop large : « liste » est un mot long,
    il tolère la variation de terminaison, et la carte accepte donc la
    réponse de sa voisine sur les compréhensions de liste.
    """
    from fabrique.verificateurs import verifier_filets

    a = {**CARTE, "id": 1, "matiere": "python", "reponse": "une liste",
         "reponses_acceptees": ["une liste", "liste"], "mots_cles": [["liste"]]}
    b = {**CARTE, "id": 2, "matiere": "python", "titre": "Autre",
         "reponse": "une liste en compréhension",
         "reponses_acceptees": ["une liste en compréhension"], "mots_cles": []}
    problemes = {s["probleme"] for s in verifier_filets([a, b])}
    assert problemes & {"filet_trop_large", "filet_englobant"}


def test_deux_cartes_de_meme_reponse_ne_font_pas_un_filet_large():
    """C'est un doublon — le contrôle 5 s'en occupe, pas celui-ci."""
    from fabrique.verificateurs import verifier_filets

    a = {**CARTE, "id": 1, "matiere": "python"}
    b = {**CARTE, "id": 2, "matiere": "python", "titre": "Bis"}
    assert not [s for s in verifier_filets([a, b])
                if s["probleme"].startswith("filet_trop")]
