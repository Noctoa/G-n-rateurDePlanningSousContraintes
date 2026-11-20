// Visualisation du planning généré : grille créneaux × terrains, vue par équipe, exports.
import { useState } from 'react'
import type { JobView, Tournament } from '../api/client.ts'
import { download, slug } from '../lib/download.ts'
import { formatDay } from '../lib/format.ts'
import {
  involves,
  placedMatches,
  poolIndex,
  teamFixtures,
  toCsv,
  toIcs,
  type PlacedMatch,
} from '../lib/schedule.ts'
import { findSlot, slotGrid } from '../lib/tournament.ts'
import { ConflictCard } from './ValidationPanel.tsx'

const POOL_COLORS = 6

function formatRest(minutes: number | null): string {
  if (minutes == null) return '—'
  if (minutes < 60) return `${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m ? `${h} h ${String(m).padStart(2, '0')}` : `${h} h`
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat">
      <dt>{label}</dt>
      <dd>{typeof value === 'number' ? value.toLocaleString('fr-FR') : value}</dd>
    </div>
  )
}

function SearchStats({ job }: { job: JobView }) {
  if (!job.stats) return null
  return (
    <>
      <Stat
        label="Temps de calcul"
        value={`${Math.round(job.stats.elapsed_ms).toLocaleString('fr-FR')} ms`}
      />
      <Stat label="Nœuds explorés" value={job.stats.nodes} />
      <Stat label="Retours arrière" value={job.stats.backtracks} />
    </>
  )
}

/** Résultat sans planning (insoluble, temps dépassé, annulé) : on explique pourquoi. */
function NoSchedule({ job }: { job: JobView }) {
  const title =
    job.status === 'infeasible'
      ? 'Aucun planning ne respecte toutes les contraintes'
      : job.status === 'timeout'
        ? 'Aucun planning trouvé dans le temps imparti'
        : job.status === 'cancelled'
          ? 'Génération annulée'
          : 'La génération a échoué'
  return (
    <div className="no-schedule">
      <p className={`status ${job.status === 'infeasible' ? 'error' : 'warning'}`}>{title}</p>
      {job.diagnosis && <p>{job.diagnosis.summary}</p>}
      {job.error && <p className="status error">{job.error}</p>}
      {job.stats && (
        <details className="technical-details">
          <summary>Détails du calcul</summary>
          <dl className="stats">
            <SearchStats job={job} />
          </dl>
        </details>
      )}
      {job.diagnosis?.conflicts.map((c, i) => (
        <ConflictCard key={i} conflict={c} />
      ))}
      {job.diagnosis?.minimal && (
        <p className="muted small">
          Ensemble minimal : retirer n’importe laquelle de ces contraintes rend le problème soluble.
        </p>
      )}
    </div>
  )
}

function MatchCard({
  placed,
  pool,
  selected,
  onSelect,
}: {
  placed: PlacedMatch
  pool: number | undefined
  selected: string
  onSelect: (teamId: string) => void
}) {
  const { match } = placed
  const focus = selected !== '' && involves(placed, selected)
  const dim = selected !== '' && !focus
  const team = (id: string, name: string) => (
    <button
      className={`card-team${id === selected ? ' current' : ''}`}
      title={`Voir le programme de ${name}`}
      onClick={() => onSelect(id === selected ? '' : id)}
    >
      {name}
    </button>
  )
  return (
    <div
      className={`match-card${focus ? ' focus' : ''}${dim ? ' dim' : ''}`}
      data-pool={pool === undefined ? undefined : pool % POOL_COLORS}
    >
      {team(match.home, placed.homeName)}
      <span className="card-vs">contre</span>
      {team(match.away, placed.awayName)}
      <span className="card-meta">
        {match.pool && `Poule ${match.pool} · `} Journée {match.round}
        {match.leg > 1 && ' retour'}
      </span>
    </div>
  )
}

function TeamProgramme({
  rows,
  teamId,
  name,
}: {
  rows: PlacedMatch[]
  teamId: string
  name: string
}) {
  const fixtures = teamFixtures(rows, teamId)
  const homeCount = fixtures.filter((f) => f.home).length
  return (
    <div className="programme">
      <h3>
        Programme de {name}{' '}
        <span className="muted small">
          {fixtures.length} matchs · {homeCount} à domicile · {fixtures.length - homeCount} à
          l’extérieur
        </span>
      </h3>
      <table className="table">
        <thead>
          <tr>
            <th>Jour</th>
            <th>Heure</th>
            <th>Terrain</th>
            <th>Adversaire</th>
            <th>Repos avant</th>
          </tr>
        </thead>
        <tbody>
          {fixtures.map((f) => (
            <tr key={f.placed.match.id}>
              <td>{formatDay(f.placed.slot.day)}</td>
              <td>
                {f.placed.slot.start.slice(0, 5)} – {f.placed.end}
              </td>
              <td>{f.placed.fieldName}</td>
              <td>
                {f.opponent} <span className="muted small">({f.home ? 'dom.' : 'ext.'})</span>
              </td>
              <td>{formatRest(f.restMinutes)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ScheduleView({ job, tournament }: { job: JobView; tournament: Tournament }) {
  const [selected, setSelected] = useState('')
  if (!job.schedule) return <NoSchedule job={job} />

  const rows = placedMatches(job, tournament)
  const pools = poolIndex(tournament)
  const { days, times } = slotGrid(tournament)
  const byCell = new Map(rows.map((p) => [`${p.slot.id}|${p.fieldId}`, p]))
  const usedSlots = new Set(rows.map((p) => p.slot.id)).size
  // L'équipe sélectionnée peut avoir disparu si le planning vient d'un autre tournoi.
  const team = tournament.teams.find((x) => x.id === selected)
  const current = team ? selected : ''
  const exported = current ? rows.filter((p) => involves(p, current)) : rows
  const fileBase = slug(team ? `${tournament.name} ${team.name}` : tournament.name)

  const byPool = new Map<string, typeof tournament.teams>()
  for (const x of tournament.teams) {
    const key = x.pool ?? ''
    byPool.set(key, [...(byPool.get(key) ?? []), x])
  }

  return (
    <div className="schedule">
      <dl className="stats">
        <Stat label="Matchs placés" value={`${rows.length} / ${job.matches.length}`} />
        <Stat label="Créneaux utilisés" value={`${usedSlots} / ${tournament.slots.length}`} />
        {job.stats && (
          <Stat
            label="Temps de calcul"
            value={`${Math.round(job.stats.elapsed_ms).toLocaleString('fr-FR')} ms`}
          />
        )}
      </dl>

      {job.violations.length > 0 && (
        <ul className="errors">
          {job.violations.map((v, i) => (
            <li key={i}>
              <b>{v.constraint}</b> {v.message}
            </li>
          ))}
        </ul>
      )}

      <div className="schedule-toolbar">
        <label className="field inline">
          <span>Afficher une équipe</span>
          <select value={current} onChange={(e) => setSelected(e.target.value)}>
            <option value="">Toutes les équipes</option>
            {[...byPool].map(([pool, teams]) => {
              const options = teams.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))
              return pool ? (
                <optgroup key={pool} label={`Poule ${pool}`}>
                  {options}
                </optgroup>
              ) : (
                options
              )
            })}
          </select>
        </label>
        {pools.size > 0 && (
          <span className="pool-legend">
            {[...pools].map(([pool, i]) => (
              <span key={pool} className="pool-chip" data-pool={i % POOL_COLORS}>
                Poule {pool}
              </span>
            ))}
          </span>
        )}
        <span className="spacer" />
        <button onClick={() => download(`${fileBase}.csv`, '﻿' + toCsv(exported), 'text/csv')}>
          Exporter CSV
        </button>
        <button
          onClick={() =>
            download(
              `${fileBase}.ics`,
              toIcs(exported, team ? `${tournament.name} – ${team.name}` : tournament.name),
              'text/calendar',
            )
          }
        >
          Exporter agenda (.ics)
        </button>
      </div>
      {team && (
        <p className="muted small">
          Les exports ne contiennent que les matchs de {team.name}. Cliquez à nouveau sur son nom
          pour revenir à toutes les équipes.
        </p>
      )}

      {team && <TeamProgramme rows={rows} teamId={team.id} name={team.name} />}

      <p className="mobile-grid-hint muted small">
        Faites défiler la grille horizontalement pour voir tous les terrains.
      </p>

      {days.map((day) => (
        <div key={day} className="day">
          <h3>{formatDay(day)}</h3>
          <div className="day-grid-wrapper">
            <table className="day-grid">
              <thead>
                <tr>
                  <th />
                  {tournament.fields.map((f) => (
                    <th key={f.id}>{f.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {times.map((time) => {
                  const slot = findSlot(tournament, day, time)
                  if (!slot) return null
                  return (
                    <tr key={time}>
                      <th>{time}</th>
                      {tournament.fields.map((f) => {
                        const placed = byCell.get(`${slot.id}|${f.id}`)
                        if (placed) {
                          return (
                            <td key={f.id}>
                              <MatchCard
                                placed={placed}
                                pool={placed.match.pool ? pools.get(placed.match.pool) : undefined}
                                selected={current}
                                onSelect={setSelected}
                              />
                            </td>
                          )
                        }
                        const closed = f.unavailable_slots?.includes(slot.id)
                        return (
                          <td key={f.id} className={closed ? 'closed' : 'free'}>
                            {closed ? 'terrain fermé' : ''}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}
      {job.stats && (
        <details className="technical-details">
          <summary>Détails du calcul</summary>
          <dl className="stats">
            <SearchStats job={job} />
          </dl>
        </details>
      )}
    </div>
  )
}
