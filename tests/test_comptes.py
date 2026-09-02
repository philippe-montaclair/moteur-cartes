"""
Tests des comptes : création, authentification, promos, RGPD.

Chaque test vise un défaut nommé. La base utilisée est celle de `conftest`,
jetable et hors du projet — jamais `prompt_app.db`.
"""

import secrets

import comptes
from comptes import ValeurRefusee

MDP = "motdepasse-assez-long"


def _identifiant(prefixe="a"):
    return f"{prefixe}-{secrets.token_hex(5)}@test.fr"


def _compte(role="apprenant"):
    return comptes.creer_compte(_identifiant(role[:3]), MDP, role=role)


# ---------------------------------------------------------------------------
# Création
# ---------------------------------------------------------------------------

def test_un_compte_se_cree():
    compte = _compte()
    assert compte["id"] and compte["role"] == "apprenant"


def test_le_hachage_ne_sort_jamais():
    """Un mot de passe qui fuit une seule fois a fui pour toujours."""
    compte = _compte()
    assert "mot_de_passe_hash" not in compte
    assert MDP not in str(compte)
    assert "mot_de_passe_hash" not in str(comptes.lire_compte(compte["id"]))


def test_le_mot_de_passe_n_est_pas_stocke_en_clair():
    identifiant = _identifiant()
    comptes.creer_compte(identifiant, MDP)
    import database
    with database.connexion(database.CHEMIN_BASE) as conn:
        empreinte = conn.execute(
            "SELECT mot_de_passe_hash FROM comptes WHERE identifiant = ?",
            (identifiant,)).fetchone()[0]
    assert MDP not in empreinte
    assert len(empreinte) > 40


def test_un_identifiant_en_double_est_refuse():
    identifiant = _identifiant()
    comptes.creer_compte(identifiant, MDP)
    try:
        comptes.creer_compte(identifiant, MDP)
    except ValeurRefusee:
        return
    raise AssertionError("doublon accepté")


def test_l_identifiant_est_insensible_a_la_casse():
    """Régression classique : « Dupont@x.fr » et « dupont@x.fr » créent deux
    comptes, l'apprenant perd sa progression et ne comprend pas pourquoi."""
    identifiant = _identifiant()
    comptes.creer_compte(identifiant, MDP)
    try:
        comptes.creer_compte(identifiant.upper(), MDP)
    except ValeurRefusee:
        return
    raise AssertionError("deux comptes pour le même identifiant à la casse près")


def test_un_mot_de_passe_trop_court_est_refuse():
    for mauvais in ("", "court", "123456789"):
        try:
            comptes.creer_compte(_identifiant(), mauvais)
        except ValeurRefusee:
            continue
        raise AssertionError(f"mot de passe {mauvais!r} accepté")


def test_un_role_inconnu_est_refuse():
    try:
        comptes.creer_compte(_identifiant(), MDP, role="dieu")
    except ValeurRefusee:
        return
    raise AssertionError("rôle inventé accepté")


# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------

def test_authentification_reussie():
    identifiant = _identifiant()
    cree = comptes.creer_compte(identifiant, MDP)
    assert comptes.authentifier(identifiant, MDP)["id"] == cree["id"]


def test_mauvais_mot_de_passe_refuse():
    identifiant = _identifiant()
    comptes.creer_compte(identifiant, MDP)
    try:
        comptes.authentifier(identifiant, MDP + "x")
    except ValeurRefusee:
        return
    raise AssertionError("mot de passe faux accepté")


def test_le_message_ne_dit_pas_si_le_compte_existe():
    """Distinguer « compte inconnu » de « mot de passe faux » dit à un inconnu
    quels comptes existent. Les deux messages doivent être identiques."""
    identifiant = _identifiant()
    comptes.creer_compte(identifiant, MDP)
    messages = set()
    for essai in ((identifiant, "faux-mot-de-passe"),
                  (_identifiant("inconnu"), MDP)):
        try:
            comptes.authentifier(*essai)
        except ValeurRefusee as erreur:
            messages.add(str(erreur))
    assert len(messages) == 1, f"messages distincts : {messages}"


def test_trop_de_tentatives_bloque():
    identifiant = _identifiant()
    comptes.creer_compte(identifiant, MDP)
    for _ in range(comptes.ECHECS_MAX):
        try:
            comptes.authentifier(identifiant, "faux")
        except ValeurRefusee:
            pass
    try:
        comptes.authentifier(identifiant, MDP)   # le BON mot de passe
    except ValeurRefusee as erreur:
        assert "tentatives" in str(erreur).lower()
        return
    raise AssertionError("la limitation n'a pas joué")


def test_une_connexion_reussie_remet_le_compteur_a_zero():
    identifiant = _identifiant()
    comptes.creer_compte(identifiant, MDP)
    for _ in range(comptes.ECHECS_MAX - 1):
        try:
            comptes.authentifier(identifiant, "faux")
        except ValeurRefusee:
            pass
    comptes.authentifier(identifiant, MDP)
    for _ in range(comptes.ECHECS_MAX - 1):
        try:
            comptes.authentifier(identifiant, "faux")
        except ValeurRefusee:
            pass
    assert comptes.authentifier(identifiant, MDP)["identifiant"] == identifiant


def test_un_compte_anonymise_ne_se_connecte_plus():
    identifiant = _identifiant()
    compte = comptes.creer_compte(identifiant, MDP)
    comptes.anonymiser(compte["id"])
    try:
        comptes.authentifier(identifiant, MDP)
    except ValeurRefusee:
        return
    raise AssertionError("un compte effacé s'est connecté")


# ---------------------------------------------------------------------------
# Promos
# ---------------------------------------------------------------------------

def test_un_apprenant_ne_cree_pas_de_promo():
    apprenant = _compte("apprenant")
    try:
        comptes.creer_promo("Promo pirate", apprenant["id"])
    except ValeurRefusee:
        return
    raise AssertionError("un apprenant a créé une promo")


def test_inscription_par_code():
    formateur = _compte("formateur")
    promo = comptes.creer_promo("Python septembre", formateur["id"])
    apprenant = _compte()
    comptes.inscrire(apprenant["id"], promo["code_invitation"])
    assert comptes.est_inscrit(apprenant["id"], promo["id"])
    assert [p["id"] for p in comptes.promos_de(apprenant["id"])] == [promo["id"]]


def test_un_code_inconnu_est_refuse():
    apprenant = _compte()
    try:
        comptes.inscrire(apprenant["id"], "code-invente")
    except ValeurRefusee:
        return
    raise AssertionError("code d'invitation inventé accepté")


def test_une_double_inscription_ne_duplique_pas():
    formateur = _compte("formateur")
    promo = comptes.creer_promo("Promo", formateur["id"])
    apprenant = _compte()
    comptes.inscrire(apprenant["id"], promo["code_invitation"])
    comptes.inscrire(apprenant["id"], promo["code_invitation"])
    assert len(comptes.promos_de(apprenant["id"])) == 1


def test_un_apprenant_suit_deux_promos_dans_le_temps():
    """Le motif du choix de la table `inscriptions` contre un `promo_id`
    nullable : un stagiaire qui revient l'année suivante garde son historique.
    """
    formateur = _compte("formateur")
    a = comptes.creer_promo("Session 1", formateur["id"])
    b = comptes.creer_promo("Session 2", formateur["id"])
    apprenant = _compte()
    comptes.inscrire(apprenant["id"], a["code_invitation"])
    comptes.inscrire(apprenant["id"], b["code_invitation"])
    assert len(comptes.promos_de(apprenant["id"])) == 2


def test_le_code_d_invitation_n_est_pas_devinable():
    formateur = _compte("formateur")
    codes = {comptes.creer_promo(f"P{i}", formateur["id"])["code_invitation"]
             for i in range(5)}
    assert len(codes) == 5
    assert all(len(c) >= 12 for c in codes)


def test_anime_la_promo_est_la_frontiere():
    a = _compte("formateur")
    b = _compte("formateur")
    promo = comptes.creer_promo("Chez A", a["id"])
    assert comptes.anime_la_promo(a["id"], promo["id"]) is True
    assert comptes.anime_la_promo(b["id"], promo["id"]) is False


def test_un_admin_voit_tout():
    formateur = _compte("formateur")
    admin = _compte("admin")
    promo = comptes.creer_promo("Chez le formateur", formateur["id"])
    assert comptes.anime_la_promo(admin["id"], promo["id"]) is True


# ---------------------------------------------------------------------------
# RGPD
# ---------------------------------------------------------------------------

def test_l_export_ne_contient_que_la_personne():
    a = _compte()
    b = _compte()
    export = comptes.exporter(a["id"])
    assert export["compte"]["id"] == a["id"]
    assert str(b["identifiant"]) not in str(export)
    assert "mot_de_passe_hash" not in str(export)


def test_l_effacement_detache_sans_detruire_les_statistiques():
    """Supprimer les tentatives détruirait les indices de qualité des
    questions, qui sont un actif produit et ne portent aucune identité une
    fois détachés."""
    import database
    import qualite
    compte = _compte()
    qualite.enregistrer_tentative(
        1, "sess-" + secrets.token_hex(4), "une réponse",
        {"correct": True, "statut": "correct"}, compte_id=compte["id"])

    with database.connexion(database.CHEMIN_BASE) as conn:
        avant = conn.execute(
            "SELECT COUNT(*) FROM tentatives WHERE compte_id = ?",
            (compte["id"],)).fetchone()[0]
    assert avant == 1

    comptes.anonymiser(compte["id"])

    with database.connexion(database.CHEMIN_BASE) as conn:
        restantes = conn.execute(
            "SELECT COUNT(*) FROM tentatives WHERE compte_id = ?",
            (compte["id"],)).fetchone()[0]
        detachees = conn.execute(
            "SELECT COUNT(*) FROM tentatives WHERE compte_id IS NULL "
            "AND reponse = ''").fetchone()[0]
    assert restantes == 0, "la tentative est restée rattachée"
    assert detachees >= 1, "la tentative a été détruite au lieu d'être détachée"


def test_l_effacement_efface_le_texte_des_reponses():
    """Une réponse écrite à la main peut contenir une donnée personnelle."""
    import database
    import qualite
    compte = _compte()
    qualite.enregistrer_tentative(
        1, "sess-" + secrets.token_hex(4), "je m'appelle Untel",
        {"correct": True, "statut": "correct"}, compte_id=compte["id"])
    comptes.anonymiser(compte["id"])
    with database.connexion(database.CHEMIN_BASE) as conn:
        restes = conn.execute(
            "SELECT COUNT(*) FROM tentatives WHERE reponse LIKE ?",
            ("%Untel%",)).fetchone()[0]
    assert restes == 0


def test_l_identifiant_est_efface_a_l_anonymisation():
    identifiant = _identifiant()
    compte = comptes.creer_compte(identifiant, MDP)
    comptes.anonymiser(compte["id"])
    relu = comptes.lire_compte(compte["id"])
    assert relu["identifiant"] != identifiant
    assert relu["anonymise"] is True
