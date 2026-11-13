// Affichage minimal du résultat d'une génération. La vraie visualisation arrive avec #9.
import type { JobView, Tournament } from '../api/client.ts'
import { findSlot, slotGrid } from '../lib/tournament.ts'
import { formatDay } from '../lib/format.ts'
import { ConflictCard } from './ValidationPanel.tsx'

const STATUS_LABEL: Record<JobView['status'], string> = {
  pending: 'En attente…',
  running: 'Recherche en cours…',
  solved: '✓ Planning trouvé',
  infeasible: '✕ Impossible',
  timeout: '⏱ Temps dépassé',
  cancelled: 'Annulé',
  error: 'Erreur',
}

export function ResultPanel({ job }: { job: JobView }) {
  const tone =
    job.status === 'solved'
      ? 'ok'
      : job.status === 'infeasible' || job.status === 'error'
        ? 'error'
        : 'warning'
  return (
    <div>
      <p className={`status ${tone}`}>{STATUS_LABEL[job.status]}</p>
      {job.diagnosis && <p>{job.diagnosis.summary}</p>}
      {job.stats && (
        <p className="muted small">
          {job.stats.nodes.toLocaleString('fr-FR')} nœuds explorés ·{' '}
          {job.stats.backtracks.toLocaleString('fr-FR')} retours arrière ·{' '}
          {job.stats.elapsed_ms.toLocaleString('fr-FR')} ms
        </p>
      )}
      {job.error && <p className="status error">{job.error}</p>}
      {job.diagnosis?.conflicts.map((c, i) => (
        <ConflictCard key={i} conflict={c} />
      ))}
      {job.violations.length > 0 && (
        <ul className="errors">
          {job.violations.map((v, i) => (
            <li key={i}>
              <b>{v.constraint}</b> {v.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function ScheduleTable({ job, tournament }: { job: JobView; tournament: Tournament }) {
  if (!job.schedule) return null
  const matches = new Map(job.matches.map((m) => [m.id, m]))
  const teamName = new Map(tournament.teams.map((t) => [t.id, t.name]))
  const at = new Map(job.schedule.assignments.map((a) => [`${a.slot_id}|${a.field_id}`, a]))
  const { days, times } = slotGrid(tournament)

  return (
    <div className="schedule">
      {days.map((day) => (
        <div key={day} className="mini-grid-wrapper">
          <h4>{formatDay(day)}</h4>
          <table className="table schedule-table">
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
                return (
                  <tr key={time}>
                    <th>{time}</th>
                    {tournament.fields.map((f) => {
                      const a = slot && at.get(`${slot.id}|${f.id}`)
                      const m = a && matches.get(a.match_id)
                      return (
                        <td key={f.id} className={m ? 'match' : 'empty'}>
                          {m ? `${teamName.get(m.home)} – ${teamName.get(m.away)}` : ''}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}
