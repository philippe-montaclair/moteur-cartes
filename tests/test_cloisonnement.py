"""
Cloisonnement — le test qui compte.

Un apprenant tente de lire, d'influencer et d'exporter les données d'un autre
par toutes les routes qui en manipulent. Chaque tentative doit renvoyer 401,
403 ou 404 — jamais une donnée.

Ces tests sont écrits pour ÉCHOUER si le cloisonnement se relâche. C'est leur
seule raison d'être : une régression ici n'est pas un bug d'affichage, c'est
une fuite de données personnelles chez un client.
"""

import secrets

import comptes
import progression as progression_mod
from app import app
from conftest import carte_par_titre

MDP = "motdepasse-assez-long"


def _identifiant(p="x"):
    return f"{p}-{secrets.token_hex(5)}@test.fr"


def _cree(role="apprenant"):
    identifiant = _identifiant(role[:3])
    compte = comptes.creer_compte(identifiant, MDP, role=role)
    return identifiant, compte


def _client(identifiant=None):
    app.config["TESTING"] = True
    client = app.test_client()
    if identifiant:
        reponse = client.post("/api/connexion", json={
            "identifiant": identifiant, "mot_de_passe": MDP})
        assert reponse.status_code == 200, reponse.get_json()
    return client


def _une_carte_id():
    return carte_par_titre("Afficher un message")["id"]


# ---------------------------------------------------------------------------
# Anonyme
# ---------------------------------------------------------------------------

def test_anonyme_refuse_sur_toutes_les_routes_privees():
    client = _client()
    for methode, route in (
        ("get", "/api/moi"),
        ("get", "/api/moi/export"),
        ("get", "/api/revision"),
        ("get", "/api/progression"),
        ("get", "/api/formateur/promos"),
        ("get", "/api/formateur/promo/1"),
        ("post", "/api/moi/suppression"),
        ("post", "/api/formateur/promos"),
    ):
        reponse = getattr(client, methode)(route, json={})
        assert reponse.status_code == 401, f"{route} a répondu {reponse.status_code}"


def test_anonyme_peut_toujours_reviser_librement():
    """Le visiteur anonyme reste servi : la correction et le catalogue ne
    demandent pas de compte. C'est le parcours d'essai."""
    client = _client()
    assert client.get("/api/cards?level=1").status_code == 200
    reponse = client.post("/api/check", json={
        "card_id": _une_carte_id(), "reponse": "print(\"Bonjour\")"})
    assert reponse.status_code == 200
    assert reponse.get_json()["progression"] is None


# ---------------------------------------------------------------------------
# Apprenant contre apprenant
# ---------------------------------------------------------------------------

def test_un_compte_id_fourni_par_le_client_est_ignore():
    """LA règle : aucune route ne lit un `compte_id` venu de la requête."""
    id_a, a = _cree()
    _id_b, b = _cree()
    client = _client(id_a)

    export = client.get(f"/api/moi/export?compte_id={b['id']}").get_json()
    assert export["compte"]["id"] == a["id"]

    moi = client.get("/api/moi").get_json()
    assert moi["compte"]["id"] == a["id"]


def test_la_progression_d_un_autre_est_inatteignable():
    id_a, a = _cree()
    _id_b, b = _cree()
    carte = _une_carte_id()
    progression_mod.enregistrer(b["id"], carte, 5)

    client = _client(id_a)
    resume = client.get("/api/progression").get_json()
    assert resume["cartes_vues"] == 0, "la progression de B a fui vers A"


def test_repondre_ne_touche_que_sa_propre_progression():
    id_a, a = _cree()
    _id_b, b = _cree()
    carte = _une_carte_id()

    client = _client(id_a)
    client.post("/api/check", json={"card_id": carte, "reponse": "n'importe quoi",
                                    "compte_id": b["id"]})

    assert progression_mod.resume(b["id"])["cartes_vues"] == 0
    assert progression_mod.resume(a["id"])["cartes_vues"] == 1


def test_l_export_d_un_autre_est_impossible():
    id_a, _a = _cree()
    _id_b, b = _cree()
    carte = _une_carte_id()
    progression_mod.enregistrer(b["id"], carte, 5)

    export = _client(id_a).get("/api/moi/export").get_json()
    assert export["progression"] == []
    assert str(b["identifiant"]) not in str(export)


def test_un_apprenant_n_atteint_pas_les_routes_formateur():
    id_a, _a = _cree("apprenant")
    _idf, formateur = _cree("formateur")
    promo = comptes.creer_promo("Promo du formateur", formateur["id"])

    client = _client(id_a)
    assert client.get("/api/formateur/promos").status_code == 403
    assert client.get(f"/api/formateur/promo/{promo['id']}").status_code == 403
    assert client.post("/api/formateur/promos",
                       json={"nom": "pirate"}).status_code == 403


def test_l_inscription_ne_permet_pas_de_choisir_son_role():
    """Sinon n'importe qui s'inscrit formateur et lit les promos qu'il crée."""
    client = _client()
    reponse = client.post("/api/inscription", json={
        "identifiant": _identifiant("role"), "mot_de_passe": MDP,
        "role": "admin"})
    assert reponse.status_code == 201
    assert reponse.get_json()["compte"]["role"] == "apprenant"


# ---------------------------------------------------------------------------
# Formateur contre formateur
# ---------------------------------------------------------------------------

def test_un_formateur_ne_voit_pas_la_promo_d_un_confrere():
    _ida, a = _cree("formateur")
    idb, _b = _cree("formateur")
    promo = comptes.creer_promo("Chez A", a["id"])

    reponse = _client(idb).get(f"/api/formateur/promo/{promo['id']}")
    assert reponse.status_code == 404, \
        "un formateur a lu la promo d'un confrère"
    assert "Chez A" not in reponse.get_data(as_text=True)


def test_une_promo_inconnue_repond_comme_une_promo_d_autrui():
    """404 et non 403 : un formateur n'a pas à apprendre qu'une promo existe
    chez un confrère. Les deux réponses doivent être indiscernables."""
    _ida, a = _cree("formateur")
    idb, _b = _cree("formateur")
    promo = comptes.creer_promo("Chez A", a["id"])
    client = _client(idb)

    chez_autrui = client.get(f"/api/formateur/promo/{promo['id']}")
    inexistante = client.get("/api/formateur/promo/999999")
    assert chez_autrui.status_code == inexistante.status_code == 404
    assert chez_autrui.get_json() == inexistante.get_json()


def test_un_formateur_voit_sa_propre_promo():
    """Le pendant du test précédent : à trop cloisonner, on ne livre rien."""
    ida, a = _cree("formateur")
    promo = comptes.creer_promo("Chez A", a["id"])
    id_eleve, eleve = _cree()
    comptes.inscrire(eleve["id"], promo["code_invitation"])

    vue = _client(ida).get(f"/api/formateur/promo/{promo['id']}").get_json()
    assert vue["promo"]["nom"] == "Chez A"
    assert [a_["id"] for a_ in vue["apprenants"]] == [eleve["id"]]
    assert "progression" in vue["apprenants"][0]


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def test_la_deconnexion_invalide_la_session():
    id_a, _a = _cree()
    client = _client(id_a)
    assert client.get("/api/moi").status_code == 200
    assert client.post("/api/deconnexion").status_code == 204
    assert client.get("/api/moi").status_code == 401


def test_un_compte_anonymise_perd_sa_session():
    id_a, a = _cree()
    client = _client(id_a)
    comptes.anonymiser(a["id"])
    assert client.get("/api/moi").status_code == 401
