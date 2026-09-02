/*
 * Interface des cartes de révision Python.
 *
 * ⚠️  AUCUNE CORRECTION DE RÉPONSE DANS CE FICHIER.
 *
 * Il n'y a volontairement pas de fonction isCorrect() ici. La correction
 * est faite par le serveur (POST /api/check), qui appelle
 * database.valider_reponse().
 *
 * C'est la cause de la panne précédente : une logique de comparaison
 * existait à la fois en Python et en JavaScript, et les deux ont divergé.
 * Résultat : des réponses justes refusées côté navigateur alors que les
 * tests Python passaient.
 *
 * Si vous devez rendre la correction plus tolérante, modifiez
 * database.py — jamais ce fichier.
 */

const $ = (id) => document.getElementById(id);

/*
 * Noms d'affichage des matières.
 *
 * La base stocke un identifiant technique (« anglais_info ») qui sert de clé
 * partout : API, fabrique, tests. On ne le renomme pas — on l'habille ici,
 * au seul endroit où un humain le lit. Une matière absente de cette table
 * s'affiche avec son identifiant nettoyé : rien ne casse si la fabrique en
 * produit une nouvelle.
 */
const MATIERES = {
  python:       { nom: 'Python',            detail: 'Les bases du langage' },
  rag:          { nom: 'RAG',               detail: 'Recherche augmentée et mesure' },
  anglais_info: { nom: 'Anglais technique', detail: "L'anglais de la documentation" },
  espagnol:     { nom: 'Espagnol',          detail: 'Vocabulaire du quotidien' },
};

function habiller(m) {
  const connu = MATIERES[m.matiere];
  return {
    nom: connu ? connu.nom : String(m.nom || m.matiere).replace(/_/g, ' '),
    detail: (connu && connu.detail) || m.description || '',
  };
}

const etat = {
  cartes: [],
  index: 0,
  bonnes: 0,
  repondu: false,
  niveau: null,
  matiere: null,
  nomMatiere: '',
  debut: 0,          // horodatage d'affichage de la carte
  indiceVu: false,
};

/*
 * Identifiant de session : jeton ALÉATOIRE et ANONYME, tiré par le navigateur.
 * Il ne contient aucune donnée personnelle — il sert uniquement à relier les
 * réponses d'un même apprenant pour calculer la discrimination des questions.
 * Sans lui, on ne pourrait mesurer que la difficulté.
 */
const sessionId = (() => {
  const cle = 'apprendre_python_session';
  const tirer = () => 'S' + Math.random().toString(36).slice(2, 12)
                          + Math.random().toString(36).slice(2, 8);
  try {
    let jeton = window.localStorage.getItem(cle);
    if (!jeton) { jeton = tirer(); window.localStorage.setItem(cle, jeton); }
    return jeton;
  } catch (e) {
    return tirer();   // navigation privée : jeton éphémère, ce n'est pas grave
  }
})();

// ---------------------------------------------------------------------------
// Appels réseau
// ---------------------------------------------------------------------------

async function api(url, options) {
  const reponse = await fetch(url, options);
  const donnees = await reponse.json().catch(() => null);
  if (!reponse.ok) {
    throw new Error((donnees && donnees.error) || `Erreur ${reponse.status}`);
  }
  return donnees;
}

function afficherErreur(message) {
  const bloc = $('erreur');
  bloc.textContent = message;
  bloc.hidden = false;
}

// ---------------------------------------------------------------------------
// Écran d'accueil
// ---------------------------------------------------------------------------

async function chargerNiveaux() {
  try {
    const niveaux = await api('/api/levels');
    const conteneur = $('liste-niveaux');
    conteneur.textContent = '';

    if (!niveaux.length) {
      conteneur.textContent = "Aucune question en base. Lancez : python database.py";
      return;
    }

    niveaux.forEach(({ niveau, total }) => {
      const bouton = document.createElement('button');
      bouton.type = 'button';
      bouton.className = 'bouton-niveau';

      const titre = document.createElement('strong');
      titre.textContent = `Niveau ${niveau}`;

      const detail = document.createElement('span');
      detail.textContent = `${total} question${total > 1 ? 's' : ''}`;

      bouton.append(titre, detail);
      bouton.addEventListener('click', () => demarrer(niveau));
      conteneur.appendChild(bouton);
    });
  } catch (e) {
    afficherErreur(`Impossible de charger les niveaux : ${e.message}`);
  }
}

// ---------------------------------------------------------------------------
// Session
// ---------------------------------------------------------------------------

function montrer(ecran) {
  ['ecran-matieres', 'ecran-accueil', 'ecran-carte', 'ecran-fin'].forEach((id) => {
    $(id).hidden = id !== ecran;
  });
}

async function chargerMatieres() {
  try {
    const matieres = await api('/api/matieres');
    const conteneur = $('liste-matieres');
    conteneur.textContent = '';

    if (!matieres.length) {
      conteneur.textContent = "Aucun contenu. Lancez : python database.py";
      return;
    }

    matieres.forEach((m) => {
      const bouton = document.createElement('button');
      bouton.type = 'button';
      bouton.className = 'bouton-niveau';
      const habit = habiller(m);
      const titre = document.createElement('strong');
      titre.textContent = habit.nom;
      const detail = document.createElement('span');
      detail.textContent = `${m.total} carte${m.total > 1 ? 's' : ''}`
        + (habit.detail ? ` · ${habit.detail}` : '')
        + (m.langue_cible ? ` · ${m.langue_cible.toUpperCase()}` : '');
      bouton.append(titre, detail);
      bouton.addEventListener('click', () => choisirMatiere(m));
      conteneur.appendChild(bouton);
    });
    montrer('ecran-matieres');
  } catch (e) {
    afficherErreur(`Impossible de charger les matières : ${e.message}`);
  }
}

function choisirMatiere(m) {
  const habit = habiller(m);
  etat.matiere = m.matiere;
  etat.nomMatiere = habit.nom;
  $('titre-matiere').textContent = habit.nom;
  $('description-matiere').textContent = habit.detail
    ? `${habit.detail} · choisir un niveau`
    : 'Choisir un niveau';

  const conteneur = $('liste-niveaux');
  conteneur.textContent = '';
  m.niveaux.forEach(({ niveau, total }) => {
    const bouton = document.createElement('button');
    bouton.type = 'button';
    bouton.className = 'bouton-niveau';
    const titre = document.createElement('strong');
    titre.textContent = `Niveau ${niveau}`;
    const detail = document.createElement('span');
    detail.textContent = `${total} question${total > 1 ? 's' : ''}`;
    bouton.append(titre, detail);
    bouton.addEventListener('click', () => demarrer(niveau));
    conteneur.appendChild(bouton);
  });
  montrer('ecran-accueil');
}

async function demarrer(niveau) {
  try {
    const melanger = $('melanger').checked ? 1 : 0;
    etat.cartes = await api(
      `/api/cards?level=${niveau}&shuffle=${melanger}`
      + (etat.matiere ? `&matiere=${encodeURIComponent(etat.matiere)}` : ''));
    etat.index = 0;
    etat.bonnes = 0;
    etat.niveau = niveau;

    if (!etat.cartes.length) {
      afficherErreur(`Le niveau ${niveau} ne contient aucune question.`);
      return;
    }

    $('erreur').hidden = true;
    montrer('ecran-carte');
    afficherCarte();
  } catch (e) {
    afficherErreur(`Impossible de démarrer : ${e.message}`);
  }
}

function afficherCarte() {
  const carte = etat.cartes[etat.index];
  etat.repondu = false;

  // Le titre nomme souvent la réponse elle-même (« Ancrage » pour
  // « l'ancrage ») : affiché avant la saisie, il donne la solution.
  // Il réapparaît dans le retour, où il sert de titre à l'explication.
  $('titre-carte').textContent = '';
  $('titre-carte').hidden = true;
  $('question').textContent = carte.question;
  $('etq-matiere').textContent = etat.nomMatiere || carte.matiere || '';
  $('categorie').textContent = carte.categorie || '—';
  $('difficulte').textContent = `Difficulté ${carte.difficulte}`;

  $('compteur').textContent = `Question ${etat.index + 1} / ${etat.cartes.length}`;
  $('score').textContent = `${etat.bonnes} bonne${etat.bonnes > 1 ? 's' : ''} réponse${etat.bonnes > 1 ? 's' : ''}`;
  $('progression-remplie').style.width =
    `${(etat.index / etat.cartes.length) * 100}%`;

  etat.debut = Date.now();
  etat.indiceVu = false;

  const saisie = $('saisie');
  saisie.value = '';
  saisie.disabled = false;
  saisie.focus();

  $('retour').hidden = true;
  $('indice').hidden = true;
  $('btn-verifier').disabled = false;
  $('btn-indice').disabled = !carte.indice;
}

// ---------------------------------------------------------------------------
// Correction — déléguée au serveur
// ---------------------------------------------------------------------------

async function verifier(event) {
  if (event) event.preventDefault();
  if (etat.repondu) return;

  const carte = etat.cartes[etat.index];
  const proposee = $('saisie').value.trim();
  if (!proposee) {
    $('saisie').focus();
    return;
  }

  $('btn-verifier').disabled = true;

  try {
    const resultat = await api('/api/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        card_id: carte.id,
        reponse: proposee,
        session_id: sessionId,
        duree_ms: Date.now() - etat.debut,
        indice_vu: etat.indiceVu,
      }),
    });

    etat.repondu = true;
    if (resultat.correct) etat.bonnes += 1;
    afficherRetour(resultat, carte);
  } catch (e) {
    $('btn-verifier').disabled = false;
    afficherErreur(`La correction a échoué : ${e.message}`);
  }
}

function remplirBloc(idBloc, idContenu, valeur) {
  const present = Boolean(valeur && String(valeur).trim());
  $(idBloc).hidden = !present;
  if (present) $(idContenu).textContent = valeur;
  return present;
}

function afficherRetour(resultat, carte) {
  // La réponse est donnée : le titre peut enfin être montré.
  $('titre-carte').textContent = carte.titre;
  $('titre-carte').hidden = false;

  const message = $('retour-message');
  // Le serveur préfixe son message d'un signe (✓ ✗ ≈). La feuille de style
  // dessine désormais ce signe elle-même, en pastille colorée : on retire
  // celui du texte pour ne pas l'afficher deux fois. Le message du serveur
  // n'est pas modifié — ses tests continuent de porter sur lui.
  message.textContent = String(resultat.message).replace(/^[✓✗≈~]\s*/, '');
  message.className = `retour-message ${resultat.statut}`;

  // Mode vocabulaire : une lettre d'écart est acceptée, mais on montre
  // toujours l'orthographe exacte — sinon on entérine la faute.
  if (resultat.orthographe_exacte && resultat.correct) {
    message.textContent += ` Orthographe exacte : ${resultat.orthographe_exacte}`;
  }

  remplirBloc('bloc-solution', 'solution', resultat.reponse);
  remplirBloc('bloc-explication', 'explication', resultat.explication);
  remplirBloc('bloc-piege', 'piege', resultat.erreur_frequente);

  const aExemple = Boolean(resultat.exemple_code);
  $('bloc-exemple').hidden = !aExemple;
  if (aExemple) {
    $('exemple').textContent = resultat.exemple_code;
    $('sortie').textContent = resultat.sortie_attendue || '(aucune sortie)';
  }

  $('saisie').disabled = true;
  $('retour').hidden = false;
  $('btn-suivant').textContent =
    etat.index + 1 < etat.cartes.length ? 'Question suivante' : 'Voir le bilan';
  $('btn-suivant').focus();
}

function suivante() {
  if (etat.index + 1 < etat.cartes.length) {
    etat.index += 1;
    afficherCarte();
  } else {
    terminer();
  }
}

function terminer() {
  const total = etat.cartes.length;
  const pourcentage = Math.round((etat.bonnes / total) * 100);
  const bilan = $('bilan');
  bilan.textContent = '';
  const chiffre = document.createElement('strong');
  chiffre.textContent = `${etat.bonnes} / ${total}`;
  bilan.append(
    chiffre,
    document.createTextNode(
      ` bonne${etat.bonnes > 1 ? 's' : ''} réponse${etat.bonnes > 1 ? 's' : ''}`
      + ` — ${pourcentage} %.`),
  );
  montrer('ecran-fin');
}

// ---------------------------------------------------------------------------
// Branchements
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  chargerMatieres();

  $('formulaire').addEventListener('submit', verifier);
  $('btn-suivant').addEventListener('click', suivante);

  $('btn-indice').addEventListener('click', () => {
    const carte = etat.cartes[etat.index];
    etat.indiceVu = true;
    $('indice').textContent = carte.indice;
    $('indice').hidden = false;
  });

  $('btn-solution').addEventListener('click', async () => {
    if (etat.repondu) return;
    etat.repondu = true;
    const carte = etat.cartes[etat.index];
    try {
      // Un abandon est une donnée pédagogique : plus d'un apprenant sur deux
      // qui renonce sur une carte, c'est le signe d'une question à revoir.
      const resultat = await api('/api/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          card_id: carte.id,
          reponse: $('saisie').value.trim(),
          revele: true,
          session_id: sessionId,
          duree_ms: Date.now() - etat.debut,
          indice_vu: etat.indiceVu,
        }),
      });
      afficherRetour(resultat, carte);
    } catch (e) {
      afficherRetour({
        statut: 'incorrect', correct: false,
        message: 'Réponse révélée — cette question ne compte pas.',
        reponse: carte.reponse, explication: carte.explication,
        exemple_code: carte.exemple_code,
        sortie_attendue: carte.sortie_attendue,
        erreur_frequente: carte.erreur_frequente,
      }, carte);
    }
  });

  $('btn-quitter').addEventListener('click', () => montrer('ecran-accueil'));
  $('btn-retour-accueil').addEventListener('click', () => montrer('ecran-accueil'));
  $('btn-changer-matiere').addEventListener('click', () => montrer('ecran-matieres'));
  $('btn-rejouer').addEventListener('click', () => demarrer(etat.niveau));

  // Ctrl/Cmd + Entrée valide depuis la zone de texte.
  $('saisie').addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') verifier(e);
  });
});
