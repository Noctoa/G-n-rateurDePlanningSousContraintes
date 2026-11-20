import type { SavedSchedule, SavedTournament } from '../api/client.ts'

const dateTime = (date: string) =>
  new Date(date).toLocaleString('fr-FR', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })

const STATUS = {
  pending: 'En attente',
  running: 'En cours',
  solved: 'Planning trouvé',
  infeasible: 'Impossible',
  timeout: 'Temps dépassé',
  cancelled: 'Annulé',
  error: 'Erreur',
}

export function TournamentLibrary({
  tournaments,
  selectedId,
  loading,
  busy,
  onOpen,
  onDelete,
  onRefresh,
}: {
  tournaments: SavedTournament[]
  selectedId: string | null
  loading: boolean
  busy: boolean
  onOpen: (id: string) => void
  onDelete: (id: string) => void
  onRefresh: () => void
}) {
  return (
    <section className="panel library" aria-labelledby="library-title">
      <div className="library-heading">
        <h2 id="library-title">
          Tournois enregistrés <span className="count-badge">{tournaments.length}</span>
        </h2>
        <button className="small" disabled={busy || loading} onClick={onRefresh}>
          Actualiser
        </button>
      </div>
      {loading ? (
        <p className="muted small" role="status">
          Chargement des tournois…
        </p>
      ) : tournaments.length === 0 ? (
        <div className="planning-empty">
          <h3>Aucun tournoi enregistré</h3>
          <p className="muted">Créez un tournoi, puis enregistrez-le pour le retrouver ici.</p>
        </div>
      ) : (
        <ul className="tournament-list">
          {tournaments.map((item) => (
            <li key={item.id} className={selectedId === item.id ? 'selected' : ''}>
              <button
                className="tournament-open"
                disabled={busy}
                aria-pressed={selectedId === item.id}
                onClick={() => onOpen(item.id)}
              >
                <span className="tournament-icon" aria-hidden="true">
                  ▦
                </span>
                <strong>{item.tournament.name}</strong>
                <span className="muted small">
                  {item.tournament.teams.length} équipes · {item.schedules_count} génération
                  {item.schedules_count !== 1 ? 's' : ''}
                </span>
                <span className="muted small">Enregistré le {dateTime(item.updated_at)}</span>
                <span className="open-label">
                  Ouvrir le tournoi <span aria-hidden="true">→</span>
                </span>
              </button>
              <button
                className="icon-button"
                disabled={busy}
                aria-label={`Supprimer ${item.tournament.name}`}
                title="Supprimer le tournoi et son historique"
                onClick={() => onDelete(item.id)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function ScheduleHistory({
  schedules,
  selectedJobId,
  loading,
  disabled,
  onOpen,
}: {
  schedules: SavedSchedule[]
  selectedJobId?: string
  loading: boolean
  disabled: boolean
  onOpen: (schedule: SavedSchedule) => void
}) {
  return (
    <section className="panel" aria-labelledby="history-title">
      <h3 id="history-title" className="sr-only">
        Choisir une génération
      </h3>
      {loading ? (
        <p className="muted small" role="status">
          Chargement de l’historique…
        </p>
      ) : schedules.length === 0 ? (
        <p className="muted small">Les générations de ce tournoi apparaîtront ici.</p>
      ) : (
        <ol className="history-list">
          {schedules.map((schedule, index) => (
            <li key={schedule.job_id}>
              <button
                className={`history-entry${schedule.job_id === selectedJobId ? ' selected' : ''}`}
                disabled={disabled}
                aria-pressed={schedule.job_id === selectedJobId}
                onClick={() => onOpen(schedule)}
              >
                <span className="library-heading">
                  <strong>Génération {schedules.length - index}</strong>
                  <span className={`history-status ${schedule.status}`}>
                    {STATUS[schedule.status]}
                  </span>
                </span>
                <span className="small muted">{dateTime(schedule.created_at)}</span>
                {schedule.stats && (
                  <span className="small muted">
                    Calculé en {Math.round(schedule.stats.elapsed_ms).toLocaleString('fr-FR')} ms
                  </span>
                )}
                <span className="small muted">
                  Limite : {schedule.timeout_seconds} s
                  {schedule.score !== null ? ` · Score : ${schedule.score}` : ''}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
