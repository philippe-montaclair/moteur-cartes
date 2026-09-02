"""Tests des routes HTTP."""

from conftest import carte_par_titre

from app import app


def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_page_accueil():
    """
    Le titre de la page n'est pas assertable : il a changé le 19 août, quand
    l'application est devenue multi-matières (« Apprendre Python » devenu
    « Cartes de révision »), et ce test échouait depuis. La passation l'a
    expliqué par un fichier non transféré dans le conteneur — vérifié le
    28 août, c'est faux : il échoue aussi avec index.html présent.

    On vérifie donc ce que la route doit garantir, et pas ce que l'éditorial
    dit : la page est servie, et elle charge bien le frontend.
    """
    reponse = client().get("/")
    assert reponse.status_code == 200
    assert b"script.js" in reponse.data
    assert b"<h1" in reponse.data


def test_liste_des_niveaux():
    donnees = client().get("/api/levels").get_json()
    assert donnees
    assert donnees[0]["niveau"] == 1
    assert donnees[0]["total"] >= 50


def test_cartes_du_niveau_1():
    donnees = client().get("/api/cards?level=1").get_json()
    assert len(donnees) >= 50
    assert all(c["niveau"] == 1 for c in donnees)
    assert {"id", "titre", "question", "reponse", "type"} <= set(donnees[0])


def test_niveau_hors_bornes_renvoie_400():
    for mauvais in (0, 8, 99):
        reponse = client().get(f"/api/cards?level={mauvais}")
        assert reponse.status_code == 400
        assert "error" in reponse.get_json()


def test_correction_bonne_reponse():
    carte = carte_par_titre("Répéter avec while")
    reponse = client().post("/api/check", json={
        "card_id": carte["id"], "reponse": "Le mot-clé est while.",
    })
    donnees = reponse.get_json()
    assert reponse.status_code == 200
    assert donnees["correct"] is True
    assert donnees["statut"] == "correct"
    assert donnees["message"].startswith("✓")
    assert donnees["explication"]


def test_correction_mauvaise_reponse():
    carte = carte_par_titre("Répéter avec while")
    donnees = client().post("/api/check", json={
        "card_id": carte["id"], "reponse": "aucune idée",
    }).get_json()
    assert donnees["correct"] is False
    assert donnees["reponse"] == "while"


def test_correction_carte_inexistante():
    reponse = client().post("/api/check", json={"card_id": 999999, "reponse": "x"})
    assert reponse.status_code == 404


def test_correction_sans_card_id():
    reponse = client().post("/api/check", json={"reponse": "x"})
    assert reponse.status_code == 400


def test_les_fichiers_sensibles_ne_sont_pas_servis():
    for chemin in ("/database.py", "/app.py", "/prompt_app.db"):
        assert client().get(chemin).status_code == 403


def test_route_de_sante():
    reponse = client().get("/api/health")
    assert reponse.status_code == 200
    assert reponse.get_json()["ok"] is True
