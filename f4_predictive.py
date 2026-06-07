"""
PROMA — F4 : Vue prédictive des tensions de recrutement
========================================================
Responsable : Stéphane
Lecture seule sur Firebase (C-4). Aucune écriture en base BAHY.

Exports publics
---------------
- run_f4()          → rapport complet (dict) — point d'entrée principal
- disponibilite()   → callable importable par Wilfriede pour F5
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────────
# Firebase — lazy import pour permettre les tests sans credentials
# ──────────────────────────────────────────────────────────────────────────────
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    _FIREBASE_AVAILABLE = True
except ImportError:
    _FIREBASE_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

SEUIL_HEURES_SEMAINE: int = 30
"""Seuil au-delà duquel un formateur est considéré non disponible (h/semaine)."""

FENETRE_SEMAINES: int = 8
"""Nombre de semaines analysées à partir d'aujourd'hui."""

ALERTE_JOURS: int = 14
"""Horizon d'alerte : formateurs qui deviennent libres dans J+ALERTE_JOURS."""

COLLECTION_EVENTS: str = "calendarEvents"
"""Nom de la collection Firebase à lire."""


# ──────────────────────────────────────────────────────────────────────────────
# Initialisation Firebase (idempotente)
# ──────────────────────────────────────────────────────────────────────────────

def _init_firebase() -> None:
    """Initialise l'app Firebase Admin une seule fois (lecture seule)."""
    if not _FIREBASE_AVAILABLE:
        raise RuntimeError(
            "firebase-admin n'est pas installé. "
            "Lancez : pip install firebase-admin --break-system-packages"
        )
    if not firebase_admin._apps:
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "serviceAccountKey.json")
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)


def _get_firestore_client():
    _init_firebase()
    return firestore.client()


# ──────────────────────────────────────────────────────────────────────────────
# Utilitaires temporels
# ──────────────────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _semaine_iso(dt: datetime) -> str:
    """Retourne la clé de semaine au format YYYY-WNN (ex: '2026-W23')."""
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _debut_semaine(dt: datetime) -> datetime:
    """Retourne le lundi de la semaine contenant dt (minuit UTC)."""
    lundi = dt - timedelta(days=dt.weekday())
    return lundi.replace(hour=0, minute=0, second=0, microsecond=0)


def _fenetre_8_semaines() -> tuple[datetime, datetime]:
    """Retourne (debut, fin) de la fenêtre de 8 semaines à partir d'aujourd'hui."""
    debut = _debut_semaine(_now_utc())
    fin = debut + timedelta(weeks=FENETRE_SEMAINES)
    return debut, fin


# ──────────────────────────────────────────────────────────────────────────────
# Lecture Firebase
# ──────────────────────────────────────────────────────────────────────────────

def _lire_calendar_events(db) -> list[dict]:
    """
    Lit la collection calendarEvents dans Firebase.
    Filtre sur la fenêtre de 8 semaines. Lecture seule (C-4).

    Champs attendus par document :
        teacherId          (str)
        start              (Timestamp | datetime | str ISO)
        end                (Timestamp | datetime | str ISO)
        hours              (int | float)
        romeCompetenciesIds (list[str])
    """
    debut_fenetre, fin_fenetre = _fenetre_8_semaines()

    query = (
        db.collection(COLLECTION_EVENTS)
        .where("start", ">=", debut_fenetre)
        .where("start", "<", fin_fenetre)
    )

    docs = query.stream()
    events = []

    for doc in docs:
        data = doc.to_dict()

        # Normalisation du champ start
        start = data.get("start")
        if hasattr(start, "ToDatetime"):
            start = start.ToDatetime(tzinfo=timezone.utc)
        elif isinstance(start, str):
            start = datetime.fromisoformat(start)
        if start and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        # Normalisation du champ end
        end = data.get("end")
        if hasattr(end, "ToDatetime"):
            end = end.ToDatetime(tzinfo=timezone.utc)
        elif isinstance(end, str):
            end = datetime.fromisoformat(end)
        if end and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        events.append({
            "teacherId": data.get("teacherId", ""),
            "start": start,
            "end": end,
            "hours": float(data.get("hours", 0)),
            "romeCompetenciesIds": data.get("romeCompetenciesIds", []),
        })

    return events


# ──────────────────────────────────────────────────────────────────────────────
# Agrégation par formateur et par semaine
# ──────────────────────────────────────────────────────────────────────────────

def _agreger_par_semaine(events: list[dict]) -> dict[str, dict[str, float]]:
    """
    Pour chaque formateur, calcule les heures occupées par semaine.

    Retourne :
        {
          "teacher_id": {
              "2026-W23": 12.0,
              "2026-W24": 35.0,
              ...
          },
          ...
        }
    """
    aggregat: dict[str, dict[str, float]] = {}

    for ev in events:
        tid = ev["teacherId"]
        start = ev["start"]
        heures = ev["hours"]

        if not tid or not start:
            continue

        semaine = _semaine_iso(start)
        aggregat.setdefault(tid, {})
        aggregat[tid][semaine] = aggregat[tid].get(semaine, 0.0) + heures

    return aggregat


def _generer_cles_semaines() -> list[str]:
    """Retourne la liste des clés de semaine sur la fenêtre de 8 semaines."""
    debut, _ = _fenetre_8_semaines()
    return [_semaine_iso(debut + timedelta(weeks=i)) for i in range(FENETRE_SEMAINES)]


# ──────────────────────────────────────────────────────────────────────────────
# Calcul de disponibilité
# ──────────────────────────────────────────────────────────────────────────────

def _heures_libres_sur_periode(
    heures_par_semaine: dict[str, float],
    debut: datetime,
    fin: datetime,
) -> float:
    """
    Calcule les heures libres (non occupées) sur une période arbitraire.
    Base : SEUIL_HEURES_SEMAINE × nombre de semaines couvertes.
    """
    semaines_couvertes: set[str] = set()
    curseur = _debut_semaine(debut)
    while curseur < fin:
        semaines_couvertes.add(_semaine_iso(curseur))
        curseur += timedelta(weeks=1)

    heures_max = SEUIL_HEURES_SEMAINE * len(semaines_couvertes)
    heures_occupees = sum(
        heures_par_semaine.get(s, 0.0) for s in semaines_couvertes
    )
    return max(0.0, heures_max - heures_occupees)


def _est_disponible_semaine(heures_par_semaine: dict[str, float], semaine: str) -> bool:
    """True si le formateur est sous le seuil pour une semaine donnée."""
    return heures_par_semaine.get(semaine, 0.0) < SEUIL_HEURES_SEMAINE


# ──────────────────────────────────────────────────────────────────────────────
# Alertes J+14
# ──────────────────────────────────────────────────────────────────────────────

def _generer_alertes_j14(
    aggregat: dict[str, dict[str, float]],
    scores_f2: Optional[dict[str, float]] = None,
) -> list[dict]:
    """
    Identifie les formateurs qui deviennent disponibles dans les 14 prochains jours.
    Trie par score F2 décroissant (ou alphabétique si scores absents).

    Retourne une liste de dicts :
        {
          "teacherId": str,
          "disponible_le": datetime,
          "semaine": str,
          "heures_libres": float,
          "score_f2": float,
          "message": str,
        }
    """
    maintenant = _now_utc()
    horizon = maintenant + timedelta(days=ALERTE_JOURS)
    alertes = []

    cles_semaines = _generer_cles_semaines()

    for teacher_id, heures_par_semaine in aggregat.items():
        for i, semaine in enumerate(cles_semaines):
            debut_sem = _debut_semaine(maintenant) + timedelta(weeks=i)

            if debut_sem > horizon:
                break

            if _est_disponible_semaine(heures_par_semaine, semaine):
                heures_libres = (
                    SEUIL_HEURES_SEMAINE - heures_par_semaine.get(semaine, 0.0)
                )
                alertes.append({
                    "teacherId": teacher_id,
                    "disponible_le": debut_sem,
                    "semaine": semaine,
                    "heures_libres": round(heures_libres, 1),
                    "score_f2": scores_f2.get(teacher_id, 0.0) if scores_f2 else 0.0,
                    "message": "ces formateurs de qualité seront disponibles bientôt",
                })
                break  # une seule alerte par formateur (première semaine libre)

    # Tri par score F2 décroissant, puis par heures libres décroissantes
    alertes.sort(key=lambda x: (-x["score_f2"], -x["heures_libres"]))

    return alertes


# ──────────────────────────────────────────────────────────────────────────────
# Vue prédictive complète sur 8 semaines
# ──────────────────────────────────────────────────────────────────────────────

def _vue_predictive_8_semaines(
    aggregat: dict[str, dict[str, float]],
) -> dict[str, list[dict]]:
    """
    Pour chaque formateur, retourne son statut semaine par semaine.

    Retourne :
        {
          "teacher_id": [
              {"semaine": "2026-W23", "heures_occupees": 12.0, "disponible": True,  "heures_libres": 18.0},
              {"semaine": "2026-W24", "heures_occupees": 35.0, "disponible": False, "heures_libres": 0.0},
              ...
          ],
          ...
        }
    """
    cles = _generer_cles_semaines()
    vue: dict[str, list[dict]] = {}

    for teacher_id, heures_par_semaine in aggregat.items():
        planning = []
        for semaine in cles:
            occupees = heures_par_semaine.get(semaine, 0.0)
            dispo = occupees < SEUIL_HEURES_SEMAINE
            planning.append({
                "semaine": semaine,
                "heures_occupees": round(occupees, 1),
                "disponible": dispo,
                "heures_libres": round(max(0.0, SEUIL_HEURES_SEMAINE - occupees), 1),
            })
        vue[teacher_id] = planning

    return vue


# ──────────────────────────────────────────────────────────────────────────────
# Fonction publique exportable — disponibilite() — pour F5 (Wilfriede)
# ──────────────────────────────────────────────────────────────────────────────

# Cache interne : évite de relire Firebase à chaque appel F5
_cache_aggregat: dict[str, dict[str, float]] = {}
_cache_expiry: Optional[datetime] = None
_CACHE_TTL_MINUTES = 10


def _get_aggregat_cached() -> dict[str, dict[str, float]]:
    """Retourne l'agrégat depuis le cache ou le recharge depuis Firebase."""
    global _cache_aggregat, _cache_expiry

    maintenant = _now_utc()
    if _cache_expiry is None or maintenant > _cache_expiry:
        db = _get_firestore_client()
        events = _lire_calendar_events(db)
        _cache_aggregat = _agreger_par_semaine(events)
        _cache_expiry = maintenant + timedelta(minutes=_CACHE_TTL_MINUTES)

    return _cache_aggregat


def disponibilite(
    teacher_id: str,
    debut: datetime,
    fin: datetime,
) -> tuple[bool, float]:
    """
    Vérifie la disponibilité d'un formateur sur une période donnée.

    Importable par Wilfriede pour F5 :
        from f4_predictive import disponibilite

    Paramètres
    ----------
    teacher_id : str
        Identifiant Firebase du formateur.
    debut : datetime
        Début de la période à vérifier (timezone-aware recommandé).
    fin : datetime
        Fin de la période à vérifier (timezone-aware recommandé).

    Retour
    ------
    (disponible: bool, heures_libres: float)
        disponible    → True si les heures occupées restent sous le seuil
        heures_libres → nombre d'heures disponibles sur la période

    Exemple
    -------
    >>> from datetime import datetime, timezone
    >>> from f4_predictive import disponibilite
    >>> dispo, heures = disponibilite("abc123", datetime(2026,6,16,tzinfo=timezone.utc), datetime(2026,6,20,tzinfo=timezone.utc))
    >>> print(dispo, heures)
    True 28.5
    """
    # Normalisation timezone
    if debut.tzinfo is None:
        debut = debut.replace(tzinfo=timezone.utc)
    if fin.tzinfo is None:
        fin = fin.replace(tzinfo=timezone.utc)

    aggregat = _get_aggregat_cached()
    heures_par_semaine = aggregat.get(teacher_id, {})
    heures_libres = _heures_libres_sur_periode(heures_par_semaine, debut, fin)

    # Un formateur est disponible si au moins une semaine de la période est sous le seuil
    semaines_periode: list[str] = []
    curseur = _debut_semaine(debut)
    while curseur < fin:
        semaines_periode.append(_semaine_iso(curseur))
        curseur += timedelta(weeks=1)

    disponible = any(
        _est_disponible_semaine(heures_par_semaine, s) for s in semaines_periode
    )

    return disponible, round(heures_libres, 1)


# ──────────────────────────────────────────────────────────────────────────────
# Point d'entrée principal — run_f4()
# ──────────────────────────────────────────────────────────────────────────────

def run_f4(scores_f2: Optional[dict[str, float]] = None) -> dict:
    """
    Point d'entrée principal de F4.

    Paramètres
    ----------
    scores_f2 : dict[str, float], optionnel
        Scores NLP issus de F2 (teacher_id → score cosinus).
        Si fourni, la liste d'alertes est triée par ce score.

    Retour
    ------
    {
        "fenetre": {"debut": datetime, "fin": datetime},
        "nb_formateurs": int,
        "vue_predictive": {teacher_id: [{"semaine", "heures_occupees", "disponible", "heures_libres"}, ...]},
        "alertes_j14": [{"teacherId", "disponible_le", "semaine", "heures_libres", "score_f2", "message"}, ...],
        "tensions": [{"semaine": str, "nb_formateurs_indisponibles": int}, ...],
    }
    """
    db = _get_firestore_client()
    events = _lire_calendar_events(db)

    # Mise à jour du cache interne (réutilisé par disponibilite())
    global _cache_aggregat, _cache_expiry
    _cache_aggregat = _agreger_par_semaine(events)
    _cache_expiry = _now_utc() + timedelta(minutes=_CACHE_TTL_MINUTES)

    aggregat = _cache_aggregat
    debut_fenetre, fin_fenetre = _fenetre_8_semaines()
    cles = _generer_cles_semaines()

    vue = _vue_predictive_8_semaines(aggregat)
    alertes = _generer_alertes_j14(aggregat, scores_f2=scores_f2)

    # Calcul des tensions : semaines où beaucoup de formateurs sont indisponibles
    tensions = []
    for semaine in cles:
        nb_indispo = sum(
            1 for heures_par_semaine in aggregat.values()
            if not _est_disponible_semaine(heures_par_semaine, semaine)
        )
        tensions.append({
            "semaine": semaine,
            "nb_formateurs_indisponibles": nb_indispo,
        })

    return {
        "fenetre": {"debut": debut_fenetre, "fin": fin_fenetre},
        "nb_formateurs": len(aggregat),
        "vue_predictive": vue,
        "alertes_j14": alertes,
        "tensions": tensions,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Mode demo / test local sans Firebase
# ──────────────────────────────────────────────────────────────────────────────

def _demo_sans_firebase() -> None:
    """
    Simule run_f4() avec des données fictives pour tester la logique sans Firebase.
    Utilisé en développement local.
    """
    maintenant = _now_utc()
    debut_s0 = _debut_semaine(maintenant)

    events_fictifs = [
        # Formateur A — très occupé semaine 0 et 1
        {"teacherId": "teacher_A", "start": debut_s0 + timedelta(days=0), "end": debut_s0 + timedelta(days=0, hours=8), "hours": 35.0, "romeCompetenciesIds": ["K1401"]},
        {"teacherId": "teacher_A", "start": debut_s0 + timedelta(weeks=1), "end": debut_s0 + timedelta(weeks=1, hours=8), "hours": 32.0, "romeCompetenciesIds": ["K1401"]},
        # Formateur B — disponible maintenant, occupé semaine 2
        {"teacherId": "teacher_B", "start": debut_s0 + timedelta(weeks=2), "end": debut_s0 + timedelta(weeks=2, hours=8), "hours": 40.0, "romeCompetenciesIds": ["K2108"]},
        # Formateur C — libre toutes les semaines
        {"teacherId": "teacher_C", "start": debut_s0 + timedelta(days=1), "end": debut_s0 + timedelta(days=1, hours=4), "hours": 10.0, "romeCompetenciesIds": ["M1202"]},
    ]

    aggregat = _agreger_par_semaine(events_fictifs)
    vue = _vue_predictive_8_semaines(aggregat)
    alertes = _generer_alertes_j14(
        aggregat,
        scores_f2={"teacher_A": 0.82, "teacher_B": 0.75, "teacher_C": 0.68},
    )

    print("=" * 60)
    print("PROMA — F4 — Vue prédictive (démo sans Firebase)")
    print("=" * 60)
    print(f"Fenêtre : {FENETRE_SEMAINES} semaines | Seuil : {SEUIL_HEURES_SEMAINE}h | Alertes J+{ALERTE_JOURS}")
    print()

    for teacher_id, planning in vue.items():
        print(f"Formateur : {teacher_id}")
        for s in planning:
            statut = "✓ LIBRE " if s["disponible"] else "✗ OCCUPÉ"
            print(f"  {s['semaine']}  {statut}  {s['heures_occupees']:5.1f}h occupées  {s['heures_libres']:5.1f}h libres")
        print()

    print(f"Alertes J+{ALERTE_JOURS} — formateurs disponibles bientôt :")
    if alertes:
        for a in alertes:
            print(f"  [{a['score_f2']:.2f}] {a['teacherId']:12s}  dispo sem. {a['semaine']}  {a['heures_libres']}h libres — {a['message']}")
    else:
        print("  Aucun formateur disponible dans les 14 prochains jours.")

    print()
    print("Test disponibilite() :")
    global _cache_aggregat
    _cache_aggregat = aggregat
    global _cache_expiry
    _cache_expiry = _now_utc() + timedelta(minutes=10)

    debut_test = debut_s0 + timedelta(weeks=3)
    fin_test = debut_test + timedelta(days=5)
    for tid in ["teacher_A", "teacher_B", "teacher_C"]:
        dispo, h = disponibilite(tid, debut_test, fin_test)
        print(f"  {tid} du {debut_test.date()} au {fin_test.date()} → dispo={dispo}, heures_libres={h}h")


if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        _demo_sans_firebase()
    else:
        rapport = run_f4()
        print(f"F4 exécuté — {rapport['nb_formateurs']} formateurs analysés")
        print(f"Alertes J+14 : {len(rapport['alertes_j14'])} formateur(s) disponible(s) bientôt")
        for alerte in rapport["alertes_j14"]:
            print(f"  [{alerte['score_f2']:.2f}] {alerte['teacherId']} — {alerte['semaine']} — {alerte['heures_libres']}h libres")
