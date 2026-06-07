# F4 — Vue prédictive PROMA

C'est ma partie dans le projet PROMA qu'on fait à l'EFREI pour le client BAHY.

PROMA c'est un système qui aide à matcher des formateurs indépendants avec des écoles, mais de façon proactive — c'est à dire qu'on anticipe les besoins avant qu'ils arrivent au lieu d'attendre le dernier moment.

Moi je gère la **F4** : la partie qui regarde les 8 prochaines semaines et qui dit "attention, là il va manquer des formateurs" ou "ces formateurs seront bientôt disponibles".

---

## Ce que fait ce module

- Il lit les événements calendrier des formateurs depuis Firebase
- Il calcule les heures occupées semaine par semaine
- Si un formateur dépasse 30h dans une semaine → il est considéré indisponible
- Il génère des alertes pour les formateurs qui se libèrent dans les 14 prochains jours
- Il trie ces formateurs par leur score de matching NLP (calculé par une autre partie du projet)
- Il expose une fonction `disponibilite()` que mon collègue Wilfriede utilise pour la partie affichage (F5)

---

## Tester sans Firebase

Pas besoin d'installer quoi que ce soit. Colle le code dans [OnlineGDB](https://www.onlinegdb.com) et lance directement.

La démo tourne avec des données fictives (3 formateurs simulés) pour montrer la logique.

```
Formateur : teacher_A
  2026-W23  ✗ OCCUPÉ   35.0h occupées    0.0h libres
  2026-W24  ✗ OCCUPÉ   32.0h occupées    0.0h libres
  2026-W25  ✓ LIBRE     0.0h occupées   30.0h libres
  ...

Alertes J+14 :
  [0.82] teacher_A  dispo sem. 2026-W25 — ces formateurs de qualité seront disponibles bientôt
  [0.75] teacher_B  dispo sem. 2026-W23 — ces formateurs de qualité seront disponibles bientôt
```

---

## Pour Wilfriede — comment appeler disponibilite()

```python
from f4_predictive import disponibilite
from datetime import datetime, timezone

dispo, heures = disponibilite("id_du_formateur", datetime(2026, 6, 16, tzinfo=timezone.utc), datetime(2026, 6, 20, tzinfo=timezone.utc))
# dispo = True ou False
# heures = nombre d'heures libres sur la période
```

---

## Avec Firebase (version réelle)

```bash
pip install firebase-admin
```

Mettre le fichier `serviceAccountKey.json` à la racine, puis :

```python
from f4_predictive import run_f4

rapport = run_f4()
```

---

## Contexte projet

EFREI Paris — ING2 PPE 2025–2026  
Client : BAHY / EduArchiv  
Ma partie : F4 (vue prédictive + alertes J+14 + fonction disponibilite pour F5)
