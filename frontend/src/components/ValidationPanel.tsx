import type { Conflict, ValidationReport } from '../api/client.ts'

export function ConflictCard({ conflict }: { conflict: Conflict }) {
  const ids = [...new Set(conflict.constraints.map((c) => c.id))]
  return (
    <div className="conflict">
      <div className="conflict-ids">
        {ids.map((id) => (
          <span key={id} className="tag danger">
            {id}
          </span>
        ))}
      </div>
      <p>{conflict.explanation}</p>
      {conflict.suggestions.length > 0 && (
        <ul className="suggestions">
          {conflict.suggestions.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function ValidationPanel({
  report,
  loading,
  error,
}: {
  report: ValidationReport | null
  loading: boolean
  error: string | null
}) {
  if (error) {
    return <p className="status error">Backend injoignable : {error}</p>
  }
  if (!report) {
    return <p className="muted">{loading ? 'Vérification…' : ''}</p>
  }
  return (
    <div className={loading ? 'stale' : ''}>
      {report.valid ? (
        <p className={`status ${report.warnings.length ? 'warning' : 'ok'}`}>
          {report.warnings.length ? '⚠ Valide mais insoluble' : '✓ Tournoi valide'}
        </p>
      ) : (
        <p className="status error">✕ {report.errors.length} erreur(s) de saisie</p>
      )}

      {report.summary && (
        <dl className="summary">
          <div>
            <dt>Équipes</dt>
            <dd>{report.summary.teams}</dd>
          </div>
          <div>
            <dt>Matchs</dt>
            <dd>{report.summary.matches}</dd>
          </div>
          <div>
            <dt>Places</dt>
            <dd title="créneaux × terrains">{report.summary.places}</dd>
          </div>
          <div>
            <dt>Créneaux</dt>
            <dd>{report.summary.slots}</dd>
          </div>
        </dl>
      )}

      {report.errors.length > 0 && (
        <ul className="errors">
          {report.errors.map((e, i) => (
            <li key={i}>
              {e.location && <code>{e.location}</code>} {e.message}
            </li>
          ))}
        </ul>
      )}

      {report.warnings.map((w, i) => (
        <ConflictCard key={i} conflict={w} />
      ))}
    </div>
  )
}
