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
  dirty,
  error,
  canSave,
  onSave,
  onOpen,
  onDelete,
  onRefresh,
}: {
  tournaments: SavedTournament[]
  selectedId: string | null
  loading: boolean
  busy: boolean
  dirty: boolean
  error: string | null
  canSave: boolean
  onSave: () => void
  onOpen: (id: string) => void
  onDelete: (id: string) => void
  onRefresh: () => void
}) {
  return (
    <section className="panel library" aria-labelledby="library-title">
      <div className="library-heading">
        <h2 id="library-title">Mes tournois</h2>
        <button className="small" disabled={busy || loading} onClick={onRefresh}>
          Actualiser
        </button>
      </div>
      <p className="muted small">
        Retrouvez vos tournois et tous leurs plannings après rechargement.
      </p>
      <div className="row wrap">
        <button className="primary" disabled={busy || !canSave} onClick={onSave}>
          {busy
            ? 'Veuillez patienter…'
            : selectedId
              ? 'Enregistrer les modifications'
              : 'Enregistrer le tournoi'}
        </button>
        <span className="muted small" role="status">
          {dirty
            ? 'Modifications non enregistrées'
            : selectedId
              ? 'Tournoi enregistré'
              : 'Brouillon local'}
        </span>
      </div>
      {error && (
        <p className="status error" role="alert">
          {error}
        </p>
      )}
      {loading ? (
        <p className="muted small" role="status">
          Chargement des tournois…
        </p>
      ) : tournaments.length === 0 ? (
        <p className="library-empty muted small">
          Aucun tournoi enregistré. Enregistrez le tournoi actuel ou générez votre premier planning.
        </p>
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
                <strong>{item.tournament.name}</strong>
                <span className="muted small">
                  {item.tournament.teams.length} équipes · {item.schedules_count} génération
                  {item.schedules_count !== 1 ? 's' : ''}
                </span>
                <span className="muted small">Enregistré le {dateTime(item.updated_at)}</span>
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
      <h2 id="history-title">Historique des générations</h2>
      <p className="muted small">
        Chaque résultat conserve les équipes, terrains et créneaux utilisés lors du calcul.
      </p>
      {loading ? (
        <p className="muted small" role="status">
          Chargement de l’historique…
        </p>
      ) : schedules.length === 0 ? (
        <p className="muted small">Les générations de ce tournoi apparaîtront ici.</p>
      ) : (
        <ol className="history-list">
          {schedules.map((schedule) => (
            <li key={schedule.job_id}>
              <button
                className={`history-entry${schedule.job_id === selectedJobId ? ' selected' : ''}`}
                disabled={disabled}
                aria-pressed={schedule.job_id === selectedJobId}
                onClick={() => onOpen(schedule)}
              >
                <span className="library-heading">
                  <strong>{dateTime(schedule.created_at)}</strong>
                  <span className={`history-status ${schedule.status}`}>
                    {STATUS[schedule.status]}
                  </span>
                </span>
                {schedule.stats && (
                  <span className="small muted">
                    {Math.round(schedule.stats.elapsed_ms).toLocaleString('fr-FR')} ms ·{' '}
                    {schedule.stats.nodes.toLocaleString('fr-FR')} nœuds ·{' '}
                    {schedule.stats.backtracks.toLocaleString('fr-FR')} retours arrière
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
