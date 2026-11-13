import { useState } from 'react'
import type { Tournament } from '../api/client.ts'
import { addTeams, removeTeam, updateTeam } from '../lib/tournament.ts'

export function TeamsEditor({
  tournament,
  onChange,
}: {
  tournament: Tournament
  onChange: (t: Tournament) => void
}) {
  const [bulk, setBulk] = useState('')
  const pools = new Set(tournament.teams.map((t) => t.pool).filter(Boolean))

  return (
    <>
      {tournament.teams.length === 0 ? (
        <p className="muted">Aucune équipe pour l’instant.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Nom</th>
              <th title="Identifiant court, utilisé dans le planning">Id</th>
              <th>Poule</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {tournament.teams.map((team, index) => (
              // Clé par position : l'id est éditable, s'en servir ferait perdre le focus.
              <tr key={index}>
                <td>
                  <input
                    value={team.name}
                    aria-label="Nom de l’équipe"
                    onChange={(e) =>
                      onChange(updateTeam(tournament, team.id, { name: e.target.value }))
                    }
                  />
                </td>
                <td>
                  <input
                    className="input-id"
                    value={team.id}
                    aria-label="Identifiant"
                    onChange={(e) =>
                      onChange(
                        updateTeam(tournament, team.id, {
                          id: e.target.value.toUpperCase().replace(/[^A-Z0-9_-]/g, ''),
                        }),
                      )
                    }
                  />
                </td>
                <td>
                  <input
                    className="input-pool"
                    value={team.pool ?? ''}
                    placeholder="—"
                    aria-label="Poule"
                    list="pools"
                    onChange={(e) =>
                      onChange(updateTeam(tournament, team.id, { pool: e.target.value || null }))
                    }
                  />
                </td>
                <td>
                  <button
                    className="icon-button"
                    title="Supprimer l’équipe"
                    onClick={() => onChange(removeTeam(tournament, team.id))}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <datalist id="pools">
        {[...pools].map((p) => (
          <option key={p} value={p!} />
        ))}
      </datalist>

      <label className="field">
        <span>Ajout rapide — une équipe par ligne, « Nom | Poule » pour préciser la poule</span>
        <textarea
          rows={3}
          value={bulk}
          placeholder={'Paris FC | A\nLyon FC | A\nNice FC | B'}
          onChange={(e) => setBulk(e.target.value)}
        />
      </label>
      <button
        disabled={!bulk.trim()}
        onClick={() => {
          onChange(addTeams(tournament, bulk))
          setBulk('')
        }}
      >
        Ajouter les équipes
      </button>
    </>
  )
}
