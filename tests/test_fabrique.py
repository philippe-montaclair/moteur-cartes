"""
Tests de la fabrique de contenu.

Le test décisif est `test_le_detecteur_repere_un_enonce_ambigu` : il rejoue
l'ancienne formulation de la carte « Parcourir un dictionnaire » — celle qui
avait passé la relecture et le contrôle d'intégrité avant qu'un apprenant ne
bute dessus — et vérifie que la fabrique l'attrape désormais toute seule.
"""

import json

import correcteur_llm as llm
import database as db
from conftest import carte_par_titre
from fabrique import verificateurs as v
from fabrique.generer import _nettoyer, construire_prompt


def fiche(**champs):
    """Carte minimale sous forme de dict, sans passer par la base."""
    base = {
        "id": 1, "matiere": "python", "langue": "fr", "niveau": 1,
        "titre": "T", "question": "Q", "reponse": "R", "categorie": "C",
        "reponses_acceptees": '["R"]', "mots_cles": "[]", "type": "texte",
        "exemple_code": "", "sortie_attendue": "",
    }
    base.update(champs)
    return base


# ---------------------------------------------------------------------------
# 3 — exécution des exemples
# ---------------------------------------------------------------------------

def test_execution_d_un_exemple():
    stdout, stderr, termine = v.executer_exemple("print('Bonjour')")
    assert termine and stdout == "Bonjour" and stderr == ""


def test_execution_interrompue_par_le_delai():
    stdout, stderr, termine = v.executer_exemple("while True: pass")
    assert termine is False
    assert "délai" in stderr


def test_une_sortie_annoncee_fausse_est_detectee():
    """Le contrôle qu'aucune relecture ne remplace."""
    c = fiche(exemple_code="print('Bonjour')", sortie_attendue="Au revoir")
    signalements = v.verifier_execution([c])
    assert len(signalements) == 1
    assert signalements[0]["probleme"] == "sortie_differente"
    assert signalements[0]["obtenu"] == "Bonjour"


def test_un_exemple_correct_ne_signale_rien():
    c = fiche(exemple_code="print('Bonjour')", sortie_attendue="Bonjour")
    assert v.verifier_execution([c]) == []


def test_une_erreur_volontaire_est_reconnue():
    """Une carte peut viser une exception : ce n'est pas un défaut."""
    c = fiche(exemple_code="print(inconnue)",
              sortie_attendue="NameError: name 'inconnue' is not defined")
    assert v.verifier_execution([c]) == []


def test_une_erreur_attendue_qui_ne_survient_pas():
    c = fiche(exemple_code="print('rien')", sortie_attendue="ZeroDivisionError")
    signalements = v.verifier_execution([c])
    assert signalements[0]["probleme"] == "erreur_attendue_absente"


def test_une_erreur_imprevue_est_signalee():
    c = fiche(exemple_code="print(1/0)", sortie_attendue="0.5")
    signalements = v.verifier_execution([c])
    assert signalements[0]["probleme"] == "exemple_en_erreur"


def test_les_exemples_interactifs_sont_ignores():
    """input() bloquerait : on ne le vérifie pas, on ne le signale pas non plus."""
    c = fiche(exemple_code="nom = input('?')\nprint(nom)", sortie_attendue="Ada")
    assert v.verifier_execution([c]) == []


def test_seules_les_matieres_declarees_executables_sont_testees():
    c = fiche(matiere="espagnol", exemple_code="print('x')", sortie_attendue="y")
    assert v.verifier_execution([c]) == []


def test_les_exemples_reels_du_projet_sont_exacts():
    """Non-régression sur tout le contenu livré."""
    assert v.verifier_execution() == []


# ---------------------------------------------------------------------------
# 5 — doublons
# ---------------------------------------------------------------------------

def test_deux_cartes_de_meme_reponse_sont_signalees():
    a = fiche(id=1, titre="A", question="Quel mot-clé répète ?", reponse="while")
    b = fiche(id=2, titre="B", question="Quel mot-clé boucle ?", reponse="while")
    problemes = {s["probleme"] for s in v.verifier_doublons([a, b])}
    assert "meme_reponse" in problemes


def test_un_gabarit_partage_ne_fait_pas_un_doublon():
    """
    Régression : « Comment dit-on *bonjour* en espagnol ? » et
    « … *merci* … » se ressemblent à 85 % comme chaînes tout en testant deux
    mots différents. Comparer les seuls énoncés produisait 79 faux positifs.
    """
    a = fiche(id=1, titre="bonjour", type="vocabulaire", langue="es",
              question="Comment dit-on « bonjour » en espagnol ?", reponse="hola")
    b = fiche(id=2, titre="merci", type="vocabulaire", langue="es",
              question="Comment dit-on « merci » en espagnol ?", reponse="gracias")
    assert v.verifier_doublons([a, b]) == []


def test_deux_niveaux_differents_ne_sont_pas_compares():
    a = fiche(id=1, niveau=1, reponse="while")
    b = fiche(id=2, niveau=2, reponse="while")
    assert v.verifier_doublons([a, b]) == []


# ---------------------------------------------------------------------------
# 4 — détecteur d'ambiguïté
# ---------------------------------------------------------------------------

class Repondeur:
    """Modèle factice : renvoie tour à tour les réponses qu'on lui donne."""

    def __init__(self, reponses):
        self.reponses = reponses
        self.appels = 0

    def __call__(self, url, charge, cle, timeout):
        rep = self.reponses[self.appels % len(self.reponses)]
        self.appels += 1
        return {"choices": [{"message": {
            "content": json.dumps({"reponse": rep})}}]}


def _avec_repondeur(reponses, carte, tirages=5):
    import os
    original = llm._requete
    llm._requete = Repondeur(reponses)
    os.environ.update({"LLM_BACKEND": "distant",
                       "LLM_URL": "http://exemple.test/v1",
                       "LLM_MODELE": "modele-test"})
    try:
        return v.verifier_ambiguite([carte], tirages=tirages, journal=lambda *a: None)
    finally:
        llm._requete = original
        for c in ("LLM_BACKEND", "LLM_URL", "LLM_MODELE"):
            os.environ.pop(c, None)


def test_une_carte_bien_posee_ne_declenche_rien():
    c = carte_par_titre("Répéter avec while")
    signalements = _avec_repondeur(
        ["while", "le mot-clé while", "while", "la boucle while", "while"], c)
    assert signalements == []


def test_le_detecteur_repere_un_enonce_ambigu():
    """
    LE test qui compte.

    On rejoue l'énoncé fautif d'origine — « Que parcourt for x in personne ? »,
    sans dire que `personne` est un dictionnaire. Un répondeur qui hésite
    entre caractères, valeurs et clés doit déclencher l'alerte.
    """
    c = fiche(
        titre="Parcourir un dictionnaire",
        question="Que parcourt une boucle for x in personne ?",
        reponse="les clés du dictionnaire",
        reponses_acceptees='["les clés du dictionnaire", "les clés"]')
    signalements = _avec_repondeur(
        ["chaque caractère", "les valeurs", "les lettres du mot",
         "les paires clé-valeur", "les index"], c)

    assert len(signalements) == 1
    assert signalements[0]["probleme"] == "enonce_ambigu"
    assert signalements[0]["gravite"] == "haute"
    assert signalements[0]["accord"] == 0.0


def test_une_reponse_attendue_trop_etroite_est_distinguee():
    """
    Signal différent : les réponses concordent entre elles mais aucune n'est
    acceptée. Ce n'est pas l'énoncé qui est flou — c'est la réponse attendue
    qui est trop étroite, voire fausse.
    """
    c = fiche(question="Quel opérateur donne le reste d'une division ?",
              reponse="modulo", reponses_acceptees='["modulo"]')
    signalements = _avec_repondeur(["%", "%", "%", "%", "%"], c)

    assert len(signalements) == 1
    assert signalements[0]["probleme"] == "reponse_attendue_trop_etroite"


def test_le_detecteur_s_arrete_proprement_sans_modele():
    import os
    os.environ["LLM_BACKEND"] = "off"
    try:
        messages = []
        assert v.verifier_ambiguite([fiche()], journal=messages.append) == []
        assert messages and "interrompu" in messages[0]
    finally:
        os.environ.pop("LLM_BACKEND", None)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def test_verifier_tout_sans_llm():
    rapport = v.verifier_tout(matiere="python", avec_llm=False,
                              journal=lambda *a: None)
    assert rapport["cartes_verifiees"] >= 50
    assert rapport["llm_utilise"] is False
    assert set(rapport["par_gravite"]) == {"haute", "moyenne", "basse"}
    assert rapport["par_gravite"]["haute"] == 0, rapport["signalements"][:3]


def test_le_contenu_livre_ne_contient_aucun_signalement_grave():
    rapport = v.verifier_tout(avec_llm=False, journal=lambda *a: None)
    graves = [s for s in rapport["signalements"] if s["gravite"] == "haute"]
    assert graves == [], graves


# ---------------------------------------------------------------------------
# Générateur
# ---------------------------------------------------------------------------

def test_nettoyage_d_une_carte_produite_par_un_modele():
    manifeste = db.lire_manifeste(db.DOSSIER_CONTENUS / "python")
    brute = {"titre": "T", "question": "Q?", "reponse": "R",
             "type": "n_importe_quoi", "difficulte": 99,
             "reponses_acceptees": "pas une liste", "bavardage": "à ignorer"}
    propre = _nettoyer(brute, manifeste, niveau=3)

    assert propre["niveau"] == 3
    assert propre["type"] == manifeste["type_defaut"]
    # Plafond porté de 5 à 10 le 28 août 2026 : le palier « expert » de la
    # matrice de difficulté vise 7 à 10. Bridée à 5, toute carte experte était
    # ramenée à « intermédiaire » sans que rien ne le signale.
    assert propre["difficulte"] == 10
    assert "R" in propre["reponses_acceptees"]
    assert "bavardage" not in propre


def test_une_carte_sans_reponse_est_ecartee():
    manifeste = db.lire_manifeste(db.DOSSIER_CONTENUS / "python")
    assert _nettoyer({"titre": "T", "question": "Q?"}, manifeste, 1) is None
    assert _nettoyer("pas un objet", manifeste, 1) is None


def test_le_prompt_de_generation_est_ancre_et_protege():
    prompt = construire_prompt(db.DOSSIER_CONTENUS / "python", 2, 5,
                               source="Texte de référence.",
                               existantes=["Afficher un message"])
    utilisateur = prompt[-1]["content"]
    assert "<<<SOURCE>>>" in utilisateur
    assert "non fiable" in utilisateur
    assert "Afficher un message" in utilisateur
    assert "AUTOPORTANT" in utilisateur


def test_le_prompt_suit_la_langue_du_paquet():
    espagnol = construire_prompt(db.DOSSIER_CONTENUS / "espagnol", 1, 3, "S")
    assert "Langue cible : espagnol" in espagnol[-1]["content"]


def test_la_source_est_tronquee():
    prompt = construire_prompt(db.DOSSIER_CONTENUS / "python", 1, 1,
                               source="z" * 50000)
    assert prompt[-1]["content"].count("z") == 12000


# ---------------------------------------------------------------------------
# 7 — le titre trahit-il la réponse ?
# ---------------------------------------------------------------------------

def test_un_titre_qui_est_la_reponse_est_signale():
    """
    Régression du 19 août 2026. 27 cartes RAG sur 30 étaient titrées du mot
    même qu'elles demandaient. La suite de tests était verte, le contrôle
    d'intégrité muet, et la vérification de la veille avait tout validé :
    elle portait sur le correcteur, jamais sur ce que l'écran montre.
    """
    carte = fiche(titre="Ancrage", reponse="l'ancrage")
    signalements = v.verifier_titre([carte])
    assert len(signalements) == 1
    assert signalements[0]["probleme"] == "titre_revele_reponse"
    # « moyenne » et non « haute » : l'affichage masque désormais le titre
    # avant la saisie, donc la carte reste livrable. Cf. verifier_titre().
    assert signalements[0]["gravite"] == "moyenne"


def test_un_article_ne_masque_pas_la_fuite():
    """« Token » et « un token » nomment la même chose : l'article ne sauve rien."""
    assert len(v.verifier_titre([fiche(titre="Token", reponse="un token")])) == 1


def test_un_titre_qui_nomme_le_theme_ne_gene_pas():
    carte = fiche(titre="Les deux phases d'un modèle", reponse="l'inférence")
    assert v.verifier_titre([carte]) == []


def test_un_noyau_trop_court_ne_suffit_pas():
    """
    « tri » se retrouve dans « trier » sans rien révéler. En dessous du seuil,
    une inclusion est une coïncidence de lettres, pas une fuite — sinon le
    contrôle crie sur tout et on apprend à ignorer le rouge.
    """
    carte = fiche(titre="Tri", reponse="trier une liste avec sorted")
    assert v.verifier_titre([carte]) == []


def test_une_carte_de_vocabulaire_bilingue_n_est_pas_signalee():
    """Le titre est en français, la réponse dans la langue cible : jamais de fuite."""
    carte = fiche(titre="bonjour", type="vocabulaire", langue="es",
                  question="Comment dit-on « bonjour » en espagnol ?",
                  reponse="hola")
    assert v.verifier_titre([carte]) == []
