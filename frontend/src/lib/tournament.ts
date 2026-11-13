// Logique d'édition d'un tournoi, sans React : fonctions pures, testables avec Node.
// Toutes les fonctions renvoient un nouveau tournoi (jamais de mutation).

import type {
  Incompatibility,
  SoftConstraintId,
  Slot,
  Team,
  Tournament,
  Venue,
} from '../api/client.ts'

// --- Contraintes souples (miroir de docs/constraints.md) -----------------------------------

export const SOFT_CONSTRAINTS: {
  id: SoftConstraintId
  label: string
  help: string
  default: number
}[] = [
  {
    id: 'S1',
    label: 'Créneaux préférés',
    help: 'Pénalité par match joué hors des créneaux préférés de l’équipe.',
    default: 3,
  },
  {
    id: 'S2',
    label: 'Équilibrage des terrains',
    help: 'Écart de charge entre les terrains.',
    default: 1,
  },
  {
    id: 'S3',
    label: 'Éviter les créneaux tardifs',
    help: 'Pénalité par match sur le dernier créneau de la journée.',
    default: 2,
  },
  {
    id: 'S4',
    label: 'Étaler sur les jours',
    help: 'Pénalité quand une équipe concentre ses matchs sur un même jour.',
    default: 2,
  },
  {
    id: 'S5',
    label: 'Éviter les longues attentes',
    help: 'Pénalité par heure d’attente au-delà de 3 h entre deux matchs le même jour.',
    default: 1,
  },
]

// --- Tournoi vide ------------------------------------------------------------------------

export function emptyTournament(): Tournament {
  const tournament: Tournament = {
    name: 'Nouveau tournoi',
    format: 'round_robin',
    teams: [],
    fields: [{ id: 'T1', name: 'Terrain 1' }],
    slots: [],
    incompatibilities: [],
    rules: { min_rest_minutes: 0, max_matches_per_team_per_day: null },
  }
  return regenerateSlots(tournament, {
    days: [nextSaturday()],
    times: ['09:00', '10:00', '11:00', '14:00', '15:00', '16:00'],
    durationMinutes: 60,
  })
}

function nextSaturday(): string {
  const d = new Date()
  d.setDate(d.getDate() + ((6 - d.getDay() + 7) % 7 || 7))
  return d.toISOString().slice(0, 10)
}

/** Nettoie un JSON importé : retire `$schema`, complète les champs optionnels. */
export function normalize(input: Tournament): Tournament {
  const { $schema: _ignored, ...rest } = input
  return {
    ...rest,
    format: rest.format ?? 'round_robin',
    incompatibilities: rest.incompatibilities ?? [],
    rules: {
      min_rest_minutes: rest.rules?.min_rest_minutes ?? 0,
      max_matches_per_team_per_day: rest.rules?.max_matches_per_team_per_day ?? null,
    },
  }
}

// --- Identifiants ------------------------------------------------------------------------

/** « Saint-Étienne FC » → « SAI ». Ajoute un suffixe numérique si déjà pris. */
export function makeId(name: string, taken: Iterable<string>, length = 3): string {
  const base =
    name
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .replace(/[^A-Za-z0-9]/g, '')
      .toUpperCase()
      .slice(0, length) || 'EQ'
  const used = new Set(taken)
  if (!used.has(base)) return base
  for (let i = 2; ; i++) {
    if (!used.has(`${base}${i}`)) return `${base}${i}`
  }
}

/** Jour n°1, 09:00 → « J1-09h » ; 09:30 → « J1-09h30 » (même schéma que les datasets). */
export function slotId(dayIndex: number, time: string): string {
  const [h, m] = time.split(':')
  return `J${dayIndex}-${h}h${m === '00' ? '' : m}`
}

// --- Équipes -----------------------------------------------------------------------------

export function addTeams(t: Tournament, lines: string): Tournament {
  const teams = [...t.teams]
  for (const raw of lines.split('\n')) {
    const [name, pool] = raw.split('|').map((part) => part.trim())
    if (!name) continue
    const team: Team = {
      id: makeId(
        name,
        teams.map((x) => x.id),
      ),
      name,
    }
    if (pool) team.pool = pool
    teams.push(team)
  }
  return { ...t, teams }
}

export function updateTeam(t: Tournament, id: string, patch: Partial<Team>): Tournament {
  const newId = patch.id
  let next: Tournament = {
    ...t,
    teams: t.teams.map((team) => (team.id === id ? { ...team, ...patch } : team)),
  }
  if (newId !== undefined && newId !== id) {
    next = {
      ...next,
      incompatibilities: (next.incompatibilities ?? []).map((inc) => ({
        ...inc,
        teams: inc.teams.map((x) => (x === id ? newId : x)) as [string, string],
      })),
    }
  }
  return next
}

export function removeTeam(t: Tournament, id: string): Tournament {
  return {
    ...t,
    teams: t.teams.filter((team) => team.id !== id),
    incompatibilities: (t.incompatibilities ?? []).filter((inc) => !inc.teams.includes(id)),
  }
}

// --- Terrains ----------------------------------------------------------------------------

export function addField(t: Tournament): Tournament {
  let n = t.fields.length + 1
  while (t.fields.some((f) => f.id === `T${n}`)) n++
  return { ...t, fields: [...t.fields, { id: `T${n}`, name: `Terrain ${n}` }] }
}

export function updateField(t: Tournament, id: string, patch: Partial<Venue>): Tournament {
  return { ...t, fields: t.fields.map((f) => (f.id === id ? { ...f, ...patch } : f)) }
}

export function removeField(t: Tournament, id: string): Tournament {
  return { ...t, fields: t.fields.filter((f) => f.id !== id) }
}

// --- Créneaux ----------------------------------------------------------------------------

export interface SlotGrid {
  days: string[]
  times: string[]
  durationMinutes: number
}

const byStart = (a: Slot, b: Slot) =>
  a.day === b.day ? a.start.localeCompare(b.start) : a.day.localeCompare(b.day)

/** Jours, heures et durée sous-jacents aux créneaux, et si ceux-ci forment une grille complète. */
export function slotGrid(t: Tournament): SlotGrid & { regular: boolean } {
  const days = [...new Set(t.slots.map((s) => s.day))].sort()
  const times = [...new Set(t.slots.map((s) => s.start.slice(0, 5)))].sort()
  const durations = new Set(t.slots.map((s) => s.duration_minutes))
  const durationMinutes = t.slots[0]?.duration_minutes ?? 60
  const regular = durations.size <= 1 && t.slots.length === days.length * times.length
  return { days, times, durationMinutes, regular }
}

export function findSlot(t: Tournament, day: string, time: string): Slot | undefined {
  return t.slots.find((s) => s.day === day && s.start.slice(0, 5) === time)
}

/**
 * Recrée les créneaux à partir de jours × heures × durée. Les quotas, indisponibilités et
 * préférences des créneaux qui existent toujours (même jour, même heure) sont conservés.
 */
export function regenerateSlots(t: Tournament, grid: SlotGrid): Tournament {
  const days = [...new Set(grid.days)].filter(Boolean).sort()
  const times = [...new Set(grid.times)].filter(Boolean).sort()
  const renamed = new Map<string, string>()
  const slots: Slot[] = []
  days.forEach((day, i) => {
    for (const time of times) {
      const id = slotId(i + 1, time)
      const previous = findSlot(t, day, time)
      if (previous) renamed.set(previous.id, id)
      const slot: Slot = { id, day, start: time, duration_minutes: grid.durationMinutes }
      if (previous?.min_matches) slot.min_matches = previous.min_matches
      if (previous?.max_matches != null) slot.max_matches = previous.max_matches
      slots.push(slot)
    }
  })
  const remap = (ids: string[] | undefined) =>
    (ids ?? []).flatMap((id) => (renamed.has(id) ? [renamed.get(id)!] : []))
  return {
    ...t,
    slots: slots.sort(byStart),
    teams: t.teams.map((team) => ({
      ...team,
      unavailable_slots: remap(team.unavailable_slots),
      preferred_slots: remap(team.preferred_slots),
    })),
    fields: t.fields.map((f) => ({ ...f, unavailable_slots: remap(f.unavailable_slots) })),
  }
}

export function setSlotQuota(
  t: Tournament,
  slotIdValue: string,
  quota: { min_matches?: number; max_matches?: number | null },
): Tournament {
  return {
    ...t,
    slots: t.slots.map((s) => {
      if (s.id !== slotIdValue) return s
      const next: Slot = { ...s, ...quota }
      if (!next.min_matches) delete next.min_matches
      if (next.max_matches == null) delete next.max_matches
      return next
    }),
  }
}

// --- Disponibilités ----------------------------------------------------------------------

export type Availability = 'free' | 'unavailable' | 'preferred'

export function teamAvailability(team: Team, slot: string): Availability {
  if (team.unavailable_slots?.includes(slot)) return 'unavailable'
  if (team.preferred_slots?.includes(slot)) return 'preferred'
  return 'free'
}

/** Cycle d'un clic : libre → indisponible → préféré → libre. */
export function cycleTeamSlot(t: Tournament, teamId: string, slot: string): Tournament {
  return {
    ...t,
    teams: t.teams.map((team) => {
      if (team.id !== teamId) return team
      const state = teamAvailability(team, slot)
      const unavailable = (team.unavailable_slots ?? []).filter((s) => s !== slot)
      const preferred = (team.preferred_slots ?? []).filter((s) => s !== slot)
      if (state === 'free') unavailable.push(slot)
      if (state === 'unavailable') preferred.push(slot)
      return { ...team, unavailable_slots: unavailable, preferred_slots: preferred }
    }),
  }
}

export function toggleFieldSlot(t: Tournament, fieldId: string, slot: string): Tournament {
  return {
    ...t,
    fields: t.fields.map((f) => {
      if (f.id !== fieldId) return f
      const current = f.unavailable_slots ?? []
      return {
        ...f,
        unavailable_slots: current.includes(slot)
          ? current.filter((s) => s !== slot)
          : [...current, slot],
      }
    }),
  }
}

// --- Incompatibilités --------------------------------------------------------------------

export function addIncompatibility(t: Tournament): Tournament {
  const [a, b] = t.teams
  if (!a || !b) return t
  const inc: Incompatibility = { teams: [a.id, b.id], reason: '' }
  return { ...t, incompatibilities: [...(t.incompatibilities ?? []), inc] }
}

export function updateIncompatibility(
  t: Tournament,
  index: number,
  patch: Partial<Incompatibility>,
): Tournament {
  return {
    ...t,
    incompatibilities: (t.incompatibilities ?? []).map((inc, i) =>
      i === index ? { ...inc, ...patch } : inc,
    ),
  }
}

export function removeIncompatibility(t: Tournament, index: number): Tournament {
  return { ...t, incompatibilities: (t.incompatibilities ?? []).filter((_, i) => i !== index) }
}

// --- Export ------------------------------------------------------------------------------

/** JSON prêt à télécharger : listes vides et valeurs par défaut retirées pour rester lisible. */
export function toExportJson(t: Tournament): string {
  const clean = <T extends object>(obj: T): T =>
    Object.fromEntries(
      Object.entries(obj).filter(([, v]) => !(Array.isArray(v) && v.length === 0) && v != null),
    ) as T
  const out: Tournament = {
    $schema: './tournament.schema.json',
    ...clean(t),
    teams: t.teams.map(clean),
    fields: t.fields.map(clean),
    slots: t.slots.map(clean),
  }
  if (!out.description) delete out.description
  if (out.rules) out.rules = clean(out.rules)
  if (out.weights && Object.keys(out.weights).length === 0) delete out.weights
  // Même ordre de clés que les datasets, pour des fichiers faciles à comparer.
  const order = ['$schema', 'name', 'description', 'format', 'teams', 'fields', 'slots']
  const sorted = Object.fromEntries(
    Object.entries(out).sort(([a], [b]) => rank(order, a) - rank(order, b)),
  )
  return JSON.stringify(sorted, null, 2) + '\n'
}

function rank(order: string[], key: string): number {
  const i = order.indexOf(key)
  return i === -1 ? order.length : i
}
