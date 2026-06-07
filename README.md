# F4 — Vue prédictive des tensions de recrutement

**Module F4 du projet PROMA** — PPE ING2 EFREI Paris 2025–2026  
Projet client : **BAHY / EduArchiv**

---

## Contexte

PROMA est un module de matching sémantique proactif intégré à **BAHY Pro**, l'outil de gestion interne de la société BAHY. Il met en relation des formateurs indépendants et des structures de formation en anticipant les besoins avant qu'ils soient exprimés.

Ce repository contient la **fonctionnalité F4** : la vue prédictive des tensions de recrutement sur les 8 prochaines semaines.

---

## Rôle de F4 dans PROMA

| Fonction | Description | Responsable |
|----------|-------------|-------------|
| F1 | Pipeline RNCP — extraction des blocs de compétences | - |
| F2 | Score de matching sémantique NLP (CamemBERT) | - |
| F3 | Comparaison NLP vs mots-clés | - |
| **F4** | **Vue prédictive des tensions — alertes J+14** | **Stéphane** |
| F5 | Interface de présentation (Streamlit) | Wilfriede |

F4 expose la fonction `disponibilite()` directement importable par F5.

---

## Ce que fait F4

- Lit la collection `calendarEvents` dans Firebase (lecture seule — contrainte C-4)
- Agrège les heures occupées par formateur et par semaine sur **8 semaines**
- Identifie les formateurs disponibles (heures occupées < **30h/semaine**)
- Génère les **alertes J+14** : formateurs qui se libèrent dans les 14 prochains jours, triés par score F2
- Expose `disponibilite()` pour que F5 puisse interroger la disponibilité de n'importe quel formateur

---

## Structure du fichier

```
f4_predictive.py
│
├── Configuration          SEUIL_HEURES_SEMAINE, FENETRE_SEMAINES, ALERTE_JOURS
├── Firebase               _init_firebase(), _lire_calendar_events()
├── Agrégation             _agreger_par_semaine(), _generer_cles_semaines()
├── Disponibilité          _heures_libres_sur_periode(), _est_disponible_semaine()
├── Alertes J+14           _generer_alertes_j14()
├── Vue prédictive         _vue_predictive_8_semaines()
├── disponibilite()        ← export public pour F5
├── run_f4()               ← point d'entrée principal
└── _demo_sans_firebase()  ← test local sans credentials
```

---

## Lancer la démo (sans Firebase)

Aucune installation requise. Copie le fichier dans [OnlineGDB](https://www.onlinegdb.com) ou n'importe quel environnement Python 3.9+, puis exécute :

```bash
python f4_predictive.py
```

Sortie attendue :

```
============================================================
PROMA — F4 — Vue prédictive (démo sans Firebase)
============================================================
Fenêtre : 8 semaines | Seuil : 30h | Alertes J+14

Formateur : teacher_A
  2026-W23  ✗ OCCUPÉ   35.0h occupées    0.0h libres
  2026-W24  ✗ OCCUPÉ   32.0h occupées    0.0h libres
  2026-W25  ✓ LIBRE     0.0h occupées   30.0h libres
  ...

Alertes J+14 — formateurs disponibles bientôt :
  [0.82] teacher_A   dispo sem. 2026-W25  30.0h libres — ces formateurs de qualité seront disponibles bientôt
  [0.75] teacher_B   dispo sem. 2026-W23  30.0h libres — ces formateurs de qualité seront disponibles bientôt
  [0.68] teacher_C   dispo sem. 2026-W23  20.0h libres — ces formateurs de qualité seront disponibles bientôt
```

---

## Utilisation avec Firebase réel

1. Installer la dépendance :

```bash
pip install firebase-admin
```

2. Poser le fichier `serviceAccountKey.json` à la racine du projet (fourni par le CTO BAHY).

3. Importer et appeler `run_f4()` :

```python
from f4_predictive import run_f4

rapport = run_f4(scores_f2={"teacher_abc": 0.82, "teacher_xyz": 0.75})
print(rapport["alertes_j14"])
```

---

## API publique — pour Wilfriede (F5)

```python
from f4_predictive import disponibilite
from datetime import datetime, timezone

dispo, heures = disponibilite(
    teacher_id="abc123",
    debut=datetime(2026, 6, 16, tzinfo=timezone.utc),
    fin=datetime(2026, 6, 20, tzinfo=timezone.utc),
)
# → (True, 28.5)
```

**Signature :** `disponibilite(teacher_id, debut, fin) → (bool, float)`

- `bool` : `True` si le formateur est disponible sur la période
- `float` : nombre d'heures libres restantes

---

## Champs Firebase attendus (`calendarEvents`)

| Champ | Type | Description |
|-------|------|-------------|
| `teacherId` | `string` | Identifiant du formateur |
| `start` | `Timestamp` | Début de l'événement |
| `end` | `Timestamp` | Fin de l'événement |
| `hours` | `number` | Heures occupées par cet événement |
| `romeCompetenciesIds` | `array<string>` | Codes ROME associés |

---

## Contraintes respectées (CDC PROMA V4)

| Réf. | Contrainte | Statut |
|------|-----------|--------|
| C-4 | Lecture seule Firebase — aucune écriture | ✅ |
| C-3 | Open source exclusivement | ✅ |
| C-5 | Compatible migration Firebase → PostgreSQL | ✅ |
| NFR-1 | Performance < 2s (embeddings cachés) | ✅ |
| F4 | Vue prédictive 8 semaines + alertes J+14 | ✅ |

---

