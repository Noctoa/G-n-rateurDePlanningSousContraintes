# Catalogue des contraintes

Ce document fixe **ce qui est obligatoire** (contraintes *dures*) et **ce qui est souhaitable**
(contraintes *souples*) dans un planning de tournoi. Chaque contrainte a un identifiant
(`H1`…, `S1`…) repris tel quel dans le code (`backend/src/planning/constraints/catalog.py`),
dans les messages d'erreur et dans l'interface.

- Une contrainte **dure** ne peut jamais être violée : un planning qui en viole une est *invalide*.
  Si aucun planning ne les respecte toutes, le tournoi est *insoluble* et on doit dire pourquoi.
- Une contrainte **souple** peut être violée, mais chaque violation coûte une **pénalité pondérée**.
  Entre deux plannings valides, le meilleur est celui de plus petit score.

## Notations

| Symbole | Sens |
|---|---|
| $M$ | matchs à placer (générés par la méthode du cercle, cf. `fixtures.py`) |
| $S$, $F$ | créneaux (`slots`) et terrains (`fields`) |
| $T(m)$ | les deux équipes du match $m$ (`home`, `away`) |
| $M_t$ | matchs de l'équipe $t$ |
| $x(m) = (s_m, f_m)$ | placement du match $m$ : son créneau et son terrain |
| $\text{start}(s)$, $\text{end}(s)$, $\text{day}(s)$ | début, fin et jour du créneau $s$ |
| $M_s$ | matchs placés sur le créneau $s$ (tous terrains confondus) |

Les créneaux ne se chevauchent jamais (c'est vérifié au chargement du tournoi), donc
« même créneau » et « en même temps » veulent dire la même chose.

## Formulation CSP

| Élément du CSP | Dans notre problème |
|---|---|
| **Variables** | un match $m \in M$ |
| **Domaine** de $m$ | les couples $(s, f) \in S \times F$, moins ceux interdits par les contraintes unaires (H3, H4) |
| **Affectation** | `Assignment(match_id, slot_id, field_id)` ; un `Schedule` complet affecte chaque match une fois |
| **Contraintes** | les prédicats H1 à H9 ci-dessous |

Taille de l'espace de recherche brut : $(|S| \cdot |F|)^{|M|}$. Pour le dataset `small`
(15 matchs, 24 couples) c'est $24^{15} \approx 5 \cdot 10^{20}$ ; pour `medium` (56 matchs, 96
couples) $96^{56} \approx 10^{111}$. D'où le besoin d'un vrai algorithme (backtracking +
propagation) plutôt que d'une énumération.

Les contraintes se classent selon leur **arité**, ce qui détermine quand le solveur peut les tester :

| Arité | Contraintes | Quand les vérifier |
|---|---|---|
| Unaire (1 match) | H3, H4 | Une seule fois, en filtrant les domaines avant la recherche |
| Binaire (2 matchs) | H1, H2, H5, H7 | À chaque affectation, contre les matchs déjà placés |
| Globale (n matchs) | H6, H8, H9 | H6 et H8 incrémentalement (compteurs) ; H9 seulement quand plus aucun match ne peut rejoindre le créneau |

## Contraintes dures

### H1 — FIELD_CAPACITY : un seul match par terrain et par créneau

- **Définition** : $\forall m \neq m' \in M,\ x(m) \neq x(m')$.
- **Exemple** : `M001` et `M007` tous deux sur `(J1-09h, T1)` → violation.
- **Paramètre** : aucun.

### H2 — TEAM_ONE_MATCH_PER_SLOT : une équipe ne joue qu'un match à la fois

- **Définition** : $\forall m \neq m',\ T(m) \cap T(m') \neq \emptyset \Rightarrow s_m \neq s_{m'}$.
- **Exemple** : `LIO–AIG` sur `(J1-10h, T1)` et `LIO–OUR` sur `(J1-10h, T2)` → violation.
- **Paramètre** : aucun.

### H3 — TEAM_UNAVAILABLE : respecter les indisponibilités des équipes

- **Définition** : $\forall m,\ \forall t \in T(m),\ s_m \notin \text{unavailable}(t)$.
- **Exemple** : `LIO` indisponible sur `J1-09h` → aucun match de `LIO` à `J1-09h`.
- **Paramètre** : `teams[].unavailable_slots`.

### H4 — FIELD_UNAVAILABLE : respecter les indisponibilités des terrains

- **Définition** : $\forall m,\ s_m \notin \text{unavailable}(f_m)$.
- **Exemple** : `T2` indisponible sur `J1-09h` (entretien) → `(J1-09h, T2)` sort de tous les domaines.
- **Paramètre** : `fields[].unavailable_slots`.

### H5 — MIN_REST : repos minimum entre deux matchs d'une équipe

- **Définition** : avec $r$ = `min_rest_minutes`, pour toute équipe $t$ et tous $m \neq m' \in M_t$
  tels que $\text{start}(s_m) \le \text{start}(s_{m'})$ : $\text{start}(s_{m'}) - \text{end}(s_m) \ge r$.
- **Exemple** : $r = 60$, créneaux d'1 h. `LIO` joue à 09:00 (fin 10:00) → son prochain match
  ne peut pas commencer avant 11:00, donc pas à 10:00.
- **Paramètre** : `rules.min_rest_minutes` (0 = désactivée, H2 suffit alors).

### H6 — MAX_MATCHES_PER_DAY : nombre maximum de matchs par équipe et par jour

- **Définition** : avec $k$ = `max_matches_per_team_per_day`,
  $\forall t, \forall d,\ |\{m \in M_t : \text{day}(s_m) = d\}| \le k$.
- **Exemple** : $k = 3$ → un 4ᵉ match de `LIO` le samedi est interdit.
- **Paramètre** : `rules.max_matches_per_team_per_day` (absent = pas de limite).

### H7 — INCOMPATIBLE_TEAMS : deux équipes incompatibles ne jouent jamais en même temps

- **Définition** : pour toute incompatibilité $\{a, b\}$, et tous $m \in M_a$, $m' \in M_b$ avec $m \neq m'$ :
  $s_m \neq s_{m'}$. (Un match `a` contre `b` est autorisé : il n'y a alors qu'un seul match.)
- **Exemple** : `LIO` et `AIG` ont le même entraîneur → `LIO–OUR` et `AIG–LOU` ne peuvent pas être
  tous les deux à `J1-14h`.
- **Paramètre** : `incompatibilities[]`.

### H8 — SLOT_QUOTA_MAX : nombre maximum de matchs sur un créneau

- **Définition** : $\forall s,\ |M_s| \le \text{max\_matches}(s)$.
- **Exemple** : `J3-17h` limité à 2 matchs (fin de tournoi) alors qu'il y a 4 terrains.
- **Paramètre** : `slots[].max_matches` (absent = limité seulement par le nombre de terrains, via H1).

### H9 — SLOT_QUOTA_MIN : nombre minimum de matchs sur un créneau

- **Définition** : $\forall s,\ |M_s| \ge \text{min\_matches}(s)$.
- **Exemple** : `J1-09h` doit avoir au moins 2 matchs (cérémonie d'ouverture, public présent).
- **Paramètre** : `slots[].min_matches` (0 par défaut).
- **Remarque** : seule contrainte qui ne peut pas être violée « par un ajout » ; sur un planning
  partiel elle n'échoue que si les matchs restants ne suffisent plus à atteindre le quota.

## Contraintes souples

Score d'un planning valide : $\text{score} = \sum_i w_i \cdot \text{pénalité}_i$, où $w_i$ est
le poids de la contrainte $S_i$ (réglable par l'utilisateur, valeurs par défaut ci-dessous).
Le détail par contrainte est conservé pour expliquer le score.

| Id | Nom | Poids par défaut |
|---|---|---|
| S1 | PREFERRED_SLOTS | 3 |
| S2 | FIELD_BALANCE | 1 |
| S3 | AVOID_LATE_SLOTS | 2 |
| S4 | SPREAD_OVER_DAYS | 2 |
| S5 | LONG_WAIT | 1 |

### S1 — PREFERRED_SLOTS : jouer sur ses créneaux préférés

- **Pénalité** : pour chaque équipe $t$ ayant des préférences, le nombre de matchs de $t$
  placés hors de `preferred_slots(t)`.
- **Exemple** : `LOU` préfère le dimanche après-midi ; 2 de ses 5 matchs y sont → pénalité 3.

### S2 — FIELD_BALANCE : répartir la charge entre les terrains

- **Pénalité** : $\sum_{f} |\,\text{charge}(f) - \overline{\text{charge}}\,|$ arrondi à l'entier,
  où $\text{charge}(f)$ est le nombre de matchs sur $f$ et $\overline{\text{charge}} = |M| / |F|$.
- **Exemple** : 15 matchs sur 2 terrains répartis 11/4 → $|11 - 7{,}5| + |4 - 7{,}5| = 7$.

### S3 — AVOID_LATE_SLOTS : éviter les derniers créneaux de la journée

- **Pénalité** : le nombre de matchs placés sur le dernier créneau de leur journée.
- **Exemple** : 3 matchs à `J1-16h` (dernier créneau du samedi) → pénalité 3.

### S4 — SPREAD_OVER_DAYS : étaler les matchs d'une équipe sur les jours

- **Pénalité** : avec $D$ le nombre de jours et $q_t = \lceil |M_t| / D \rceil$, la somme sur les
  équipes et les jours de $\max(0,\ |\{m \in M_t : \text{day}(s_m) = d\}| - q_t)$.
- **Exemple** : 5 matchs sur 2 jours → $q = 3$ ; 4 le samedi et 1 le dimanche → pénalité 1.

### S5 — LONG_WAIT : éviter les longues attentes entre deux matchs le même jour

- **Pénalité** : pour deux matchs consécutifs d'une équipe **le même jour**, chaque heure
  entamée d'attente au-delà de 3 h (entre la fin de l'un et le début de l'autre).
- **Exemple** : `LIO` finit à 10:00 et rejoue à 15:00 → 5 h d'attente → pénalité 2.

## Vérifications d'insolubilité évidentes

Avant de lancer la recherche, des conditions nécessaires simples permettent de conclure tout de suite
(et d'expliquer pourquoi, cf. #6) :

- **Capacité** : $|M| \le$ nombre de couples $(s, f)$ disponibles (après H4 et H8). C'est le cas du
  dataset `unsolvable` : 15 matchs pour 12 places.
- **Domaine vide** : un match dont tous les couples sont éliminés par H3/H4.
- **Capacité par équipe** : une équipe doit avoir au moins $|M_t|$ créneaux disponibles, et au plus
  $k$ matchs par jour (H6) sur ses jours disponibles.
- **Quotas minimum** : $\sum_s \text{min\_matches}(s) \le |M|$.

Ces tests ne sont pas suffisants : un tournoi qui les passe peut quand même être insoluble, ce que
seule la recherche complète peut établir. Dans ce cas, un **filtre par suppression** retire les
contraintes une à une et relance la recherche : celles dont le retrait rend le problème soluble
forment un sous-ensemble minimal de règles incompatibles, présenté à l'utilisateur avec des
suggestions. Implémentation : `backend/src/planning/diagnosis.py` et `planner.py`.

Exemple (3 équipes, 3 créneaux d'1 h consécutifs, 60 min de repos) : chaque équipe n'a besoin que
de 2 créneaux espacés et en a 2 (09:00 et 11:00), donc les pré-vérifications passent ; mais les 3
matchs partagent deux à deux une équipe et devraient tous être espacés d'1 h, ce qui demande 3
créneaux. Le filtre isole les trois règles de repos (H5).

Le diagnostic distingue toujours **impossible** (prouvé) et **inconnu** (timeout).
