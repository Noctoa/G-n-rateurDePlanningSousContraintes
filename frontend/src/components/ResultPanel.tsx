// Statut court de la génération dans la barre latérale ; le détail est dans ScheduleView.
import type { JobView } from '../api/client.ts'

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
  const final = job.status !== 'pending' && job.status !== 'running'
  return (
    <div>
      <p className={`status ${tone}`}>{STATUS_LABEL[job.status]}</p>
      {job.diagnosis && <p className="small">{job.diagnosis.summary}</p>}
      {job.stats && (
        <p className="muted small">
          {job.stats.nodes.toLocaleString('fr-FR')} nœuds ·{' '}
          {job.stats.backtracks.toLocaleString('fr-FR')} retours arrière ·{' '}
          {Math.round(job.stats.elapsed_ms).toLocaleString('fr-FR')} ms
        </p>
      )}
      {final && (
        <a className="small" href="#resultat">
          {job.schedule ? 'Voir le planning ↓' : 'Voir le diagnostic ↓'}
        </a>
      )}
    </div>
  )
}
