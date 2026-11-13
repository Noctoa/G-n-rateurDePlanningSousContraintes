import { useState } from 'react'
import type { Tournament } from '../api/client.ts'
import {
  cycleTeamSlot,
  findSlot,
  setSlotQuota,
  slotGrid,
  teamAvailability,
  toggleFieldSlot,
} from '../lib/tournament.ts'
import { formatDay } from '../lib/format.ts'

type Target = { kind: 'team' | 'field'; id: string } | { kind: 'quotas' }

function targetKey(t: Target): string {
  return t.kind === 'quotas' ? 'quotas' : `${t.kind}:${t.id}`
}

export function AvailabilityGrid({
  tournament,
  onChange,
}: {
  tournament: Tournament
  onChange: (t: Tournament) => void
}) {
  const [target, setTarget] = useState<Target>(() =>
    tournament.teams[0] ? { kind: 'team', id: tournament.teams[0].id } : { kind: 'quotas' },
  )
  const { days, times } = slotGrid(tournament)

  // La cible peut disparaître (équipe supprimée, import) : on retombe sur les quotas.
  const exists =
    target.kind === 'quotas' ||
    (target.kind === 'team' ? tournament.teams : tournament.fields).some((x) => x.id === target.id)
  const current: Target = exists ? target : { kind: 'quotas' }
  const team = current.kind === 'team' ? tournament.teams.find((x) => x.id === current.id) : null
  const field = current.kind === 'field' ? tournament.fields.find((x) => x.id === current.id) : null

  const options: { key: string; label: string; target: Target }[] = [
    ...tournament.teams.map((x) => {
      const n = (x.unavailable_slots?.length ?? 0) + (x.preferred_slots?.length ?? 0)
      return {
        key: `team:${x.id}`,
        label: `Équipe — ${x.name}${n ? ` (${n})` : ''}`,
        target: { kind: 'team' as const, id: x.id },
      }
    }),
    ...tournament.fields.map((x) => {
      const n = x.unavailable_slots?.length ?? 0
      return {
        key: `field:${x.id}`,
        label: `Terrain — ${x.name}${n ? ` (${n})` : ''}`,
        target: { kind: 'field' as const, id: x.id },
      }
    }),
    { key: 'quotas', label: 'Quotas de matchs par créneau', target: { kind: 'quotas' } },
  ]

  return (
    <>
      <div className="row wrap">
        <select
          value={targetKey(current)}
          aria-label="Quoi éditer"
          onChange={(e) => setTarget(options.find((o) => o.key === e.target.value)!.target)}
        >
          {options.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </select>
        <span className="legend">
          {current.kind === 'team' && (
            <>
              Clic : <span className="cell-sample free">libre</span> →{' '}
              <span className="cell-sample unavailable">indisponible</span> →{' '}
              <span className="cell-sample preferred">préféré</span>
            </>
          )}
          {current.kind === 'field' && (
            <>
              Clic : <span className="cell-sample free">libre</span> ↔{' '}
              <span className="cell-sample unavailable">indisponible</span>
            </>
          )}
          {current.kind === 'quotas' && (
            <>Minimum et maximum de matchs sur le créneau (vide = libre)</>
          )}
        </span>
      </div>

      <div className="mini-grid-wrapper">
        <table className="mini-grid">
          <thead>
            <tr>
              <th />
              {days.map((d) => (
                <th key={d}>{formatDay(d)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {times.map((time) => (
              <tr key={time}>
                <th>{time}</th>
                {days.map((day) => {
                  const slot = findSlot(tournament, day, time)
                  if (!slot) return <td key={day} className="cell missing" />
                  if (current.kind === 'quotas') {
                    return (
                      <td key={day} className="cell">
                        <div className="quotas">
                          <input
                            type="number"
                            min={0}
                            placeholder="min"
                            aria-label={`Minimum ${slot.id}`}
                            value={slot.min_matches || ''}
                            onChange={(e) =>
                              onChange(
                                setSlotQuota(tournament, slot.id, {
                                  min_matches: Number(e.target.value) || 0,
                                }),
                              )
                            }
                          />
                          <input
                            type="number"
                            min={0}
                            placeholder="max"
                            aria-label={`Maximum ${slot.id}`}
                            value={slot.max_matches ?? ''}
                            onChange={(e) =>
                              onChange(
                                setSlotQuota(tournament, slot.id, {
                                  max_matches:
                                    e.target.value === '' ? null : Number(e.target.value),
                                }),
                              )
                            }
                          />
                        </div>
                      </td>
                    )
                  }
                  const state = team
                    ? teamAvailability(team, slot.id)
                    : field?.unavailable_slots?.includes(slot.id)
                      ? 'unavailable'
                      : 'free'
                  return (
                    <td key={day} className={`cell ${state}`}>
                      <button
                        title={`${slot.id} : ${state === 'free' ? 'libre' : state === 'unavailable' ? 'indisponible' : 'préféré'}`}
                        onClick={() =>
                          onChange(
                            team
                              ? cycleTeamSlot(tournament, team.id, slot.id)
                              : toggleFieldSlot(tournament, field!.id, slot.id),
                          )
                        }
                      >
                        {state === 'unavailable' ? '✕' : state === 'preferred' ? '★' : ''}
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
