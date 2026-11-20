import type { Tournament } from '../api/client.ts'
import {
  SOFT_CONSTRAINTS,
  addIncompatibility,
  removeIncompatibility,
  updateIncompatibility,
} from '../lib/tournament.ts'

export function HardRulesEditor({
  tournament,
  onChange,
}: {
  tournament: Tournament
  onChange: (t: Tournament) => void
}) {
  const rules = tournament.rules ?? {}
  const incompatibilities = tournament.incompatibilities ?? []
  const setRules = (patch: Partial<NonNullable<Tournament['rules']>>) =>
    onChange({ ...tournament, rules: { ...rules, ...patch } })

  return (
    <>
      <div className="grid-2">
        <label className="field">
          <span>Repos minimum entre deux matchs</span>
          <span className="muted small">Pour une même équipe, en minutes.</span>
          <span className="row">
            <input
              type="number"
              min={0}
              step={15}
              value={rules.min_rest_minutes ?? 0}
              onChange={(e) => setRules({ min_rest_minutes: Math.max(0, Number(e.target.value)) })}
            />
            <span className="muted">min</span>
          </span>
        </label>
        <label className="field">
          <span>Matchs maximum par jour</span>
          <span className="muted small">Pour chaque équipe. Laissez vide pour ne pas limiter.</span>
          <input
            type="number"
            min={1}
            placeholder="sans limite"
            value={rules.max_matches_per_team_per_day ?? ''}
            onChange={(e) =>
              setRules({
                max_matches_per_team_per_day:
                  e.target.value === '' ? null : Math.max(1, Number(e.target.value)),
              })
            }
          />
        </label>
      </div>

      <h4>Équipes qui ne peuvent pas jouer en même temps</h4>
      <p className="muted small">Par exemple, deux équipes qui partagent le même entraîneur.</p>
      {incompatibilities.length === 0 && <p className="muted small">Aucune.</p>}
      <ul className="chips-list">
        {incompatibilities.map((inc, i) => (
          <li key={i} className="row wrap">
            {[0, 1].map((side) => (
              <select
                key={side}
                value={inc.teams[side]}
                aria-label={`Équipe ${side + 1}`}
                onChange={(e) => {
                  const teams = [...inc.teams] as [string, string]
                  teams[side] = e.target.value
                  onChange(updateIncompatibility(tournament, i, { teams }))
                }}
              >
                {tournament.teams.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            ))}
            <input
              placeholder="raison (facultatif)"
              value={inc.reason ?? ''}
              onChange={(e) =>
                onChange(updateIncompatibility(tournament, i, { reason: e.target.value }))
              }
            />
            <button
              className="icon-button"
              title="Retirer"
              onClick={() => onChange(removeIncompatibility(tournament, i))}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
      <button
        disabled={tournament.teams.length < 2}
        onClick={() => onChange(addIncompatibility(tournament))}
      >
        Ajouter une incompatibilité
      </button>
      <p className="muted small">
        Pour bloquer un horaire précis, ouvrez la section « Disponibilités ».
      </p>
    </>
  )
}

export function SoftWeightsEditor({
  tournament,
  onChange,
}: {
  tournament: Tournament
  onChange: (t: Tournament) => void
}) {
  const weights = tournament.weights ?? {}
  return (
    <>
      <p className="muted small">
        Préférences à satisfaire au mieux. Plus le poids est élevé, plus la règle compte ; 0 la
        désactive.
      </p>
      <table className="table">
        <tbody>
          {SOFT_CONSTRAINTS.map((c) => {
            const value = weights[c.id] ?? c.default
            return (
              <tr key={c.id}>
                <td>
                  <strong>{c.label}</strong>
                  <div className="muted small">{c.help}</div>
                </td>
                <td className="weight">
                  <input
                    type="range"
                    min={0}
                    max={10}
                    value={value}
                    aria-label={`Importance : ${c.label}`}
                    onChange={(e) => {
                      const next = { ...weights, [c.id]: Number(e.target.value) }
                      if (next[c.id] === c.default) delete next[c.id]
                      onChange({ ...tournament, weights: next })
                    }}
                  />
                  <span className="weight-value">{value}</span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </>
  )
}
