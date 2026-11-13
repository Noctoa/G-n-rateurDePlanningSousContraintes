// Logique pure autour d'un planning généré : lignes placées, programme d'une équipe, exports.
import type { JobView, Match, Slot, Tournament } from '../api/client.ts'
import { slug } from './download.ts'

export interface PlacedMatch {
  match: Match
  slot: Slot
  fieldId: string
  fieldName: string
  homeName: string
  awayName: string
  /** Heure de fin « HH:MM » (début + durée du créneau). */
  end: string
}

function addMinutes(time: string, minutes: number): string {
  const [h, m] = time.split(':').map(Number)
  const total = h * 60 + m + minutes
  return `${String(Math.floor(total / 60) % 24).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

const minutesOf = (slot: Slot) => {
  const [h, m] = slot.start.split(':').map(Number)
  return h * 60 + m
}

/** Matchs placés, triés par jour, heure puis ordre des terrains. */
export function placedMatches(job: JobView, t: Tournament): PlacedMatch[] {
  if (!job.schedule) return []
  const matches = new Map(job.matches.map((m) => [m.id, m]))
  const slots = new Map(t.slots.map((s) => [s.id, s]))
  const fieldIndex = new Map(t.fields.map((f, i) => [f.id, i]))
  const fieldName = new Map(t.fields.map((f) => [f.id, f.name]))
  const teamName = new Map(t.teams.map((x) => [x.id, x.name]))

  const rows: PlacedMatch[] = []
  for (const a of job.schedule.assignments) {
    const match = matches.get(a.match_id)
    const slot = slots.get(a.slot_id)
    if (!match || !slot) continue
    rows.push({
      match,
      slot,
      fieldId: a.field_id,
      fieldName: fieldName.get(a.field_id) ?? a.field_id,
      homeName: teamName.get(match.home) ?? match.home,
      awayName: teamName.get(match.away) ?? match.away,
      end: addMinutes(slot.start.slice(0, 5), slot.duration_minutes),
    })
  }
  return rows.sort(
    (x, y) =>
      x.slot.day.localeCompare(y.slot.day) ||
      x.slot.start.localeCompare(y.slot.start) ||
      (fieldIndex.get(x.fieldId) ?? 0) - (fieldIndex.get(y.fieldId) ?? 0),
  )
}

export const involves = (p: PlacedMatch, teamId: string) =>
  p.match.home === teamId || p.match.away === teamId

export interface TeamFixture {
  placed: PlacedMatch
  opponent: string
  home: boolean
  /** Minutes de repos depuis la fin du match précédent le même jour (null si premier du jour). */
  restMinutes: number | null
}

/** Programme chronologique d'une équipe, avec le repos entre deux matchs d'une même journée. */
export function teamFixtures(rows: PlacedMatch[], teamId: string): TeamFixture[] {
  const fixtures: TeamFixture[] = []
  let previous: PlacedMatch | null = null
  for (const p of rows) {
    if (!involves(p, teamId)) continue
    const home = p.match.home === teamId
    const restMinutes =
      previous && previous.slot.day === p.slot.day
        ? minutesOf(p.slot) - (minutesOf(previous.slot) + previous.slot.duration_minutes)
        : null
    fixtures.push({ placed: p, opponent: home ? p.awayName : p.homeName, home, restMinutes })
    previous = p
  }
  return fixtures
}

/** Couleur stable par poule (index dans la liste triée des poules). */
export function poolIndex(t: Tournament): Map<string, number> {
  const pools = [...new Set(t.teams.map((x) => x.pool).filter((p): p is string => !!p))].sort()
  return new Map(pools.map((p, i) => [p, i]))
}

// --- Exports -----------------------------------------------------------------------------

function csvCell(value: string | number | null): string {
  const text = value == null ? '' : String(value)
  return /[";\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/** CSV séparé par « ; » (ouvre directement dans un tableur configuré en français). */
export function toCsv(rows: PlacedMatch[]): string {
  const header = [
    'match',
    'jour',
    'debut',
    'fin',
    'terrain',
    'domicile',
    'exterieur',
    'poule',
    'journee',
    'manche',
  ]
  const lines = rows.map((p) =>
    [
      p.match.id,
      p.slot.day,
      p.slot.start.slice(0, 5),
      p.end,
      p.fieldName,
      p.homeName,
      p.awayName,
      p.match.pool,
      p.match.round,
      p.match.leg,
    ]
      .map(csvCell)
      .join(';'),
  )
  return [header.join(';'), ...lines].join('\r\n') + '\r\n'
}

function icsText(value: string): string {
  return value
    .replace(/\\/g, '\\\\')
    .replace(/\n/g, '\\n')
    .replace(/([,;])/g, '\\$1')
}

/** Coupe les lignes à 75 octets comme l'exige la RFC 5545. */
function fold(line: string): string {
  const bytes = new TextEncoder().encode(line)
  if (bytes.length <= 75) return line
  const parts: string[] = []
  let current = ''
  let size = 0
  for (const char of line) {
    const n = new TextEncoder().encode(char).length
    if (size + n > (parts.length ? 74 : 75)) {
      parts.push(current)
      current = ''
      size = 0
    }
    current += char
    size += n
  }
  parts.push(current)
  return parts.join('\r\n ')
}

const icsDate = (day: string, time: string) => `${day.replace(/-/g, '')}T${time.replace(':', '')}00`

/**
 * Calendrier iCalendar (.ics) : un événement par match, en heure locale « flottante »
 * (le tournoi n'indique pas de fuseau, l'agenda l'affiche à l'heure prévue).
 */
export function toIcs(rows: PlacedMatch[], tournamentName: string, now = new Date()): string {
  const stamp = now
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d{3}/, '')
  const uidBase = slug(tournamentName)
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Planning sous contraintes//FR',
    'CALSCALE:GREGORIAN',
    `X-WR-CALNAME:${icsText(tournamentName)}`,
  ]
  for (const p of rows) {
    const description = [
      `Match ${p.match.id}`,
      p.match.pool ? `Poule ${p.match.pool}` : null,
      `Journée ${p.match.round}`,
    ]
      .filter(Boolean)
      .join(' · ')
    lines.push(
      'BEGIN:VEVENT',
      `UID:${p.match.id}@${uidBase}`,
      `DTSTAMP:${stamp}`,
      `DTSTART:${icsDate(p.slot.day, p.slot.start.slice(0, 5))}`,
      `DTEND:${icsDate(p.slot.day, p.end)}`,
      `SUMMARY:${icsText(`${p.homeName} – ${p.awayName}`)}`,
      `LOCATION:${icsText(p.fieldName)}`,
      `DESCRIPTION:${icsText(description)}`,
      'END:VEVENT',
    )
  }
  lines.push('END:VCALENDAR')
  return lines.map(fold).join('\r\n') + '\r\n'
}
