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
          <span>
            <b>H5</b> Repos minimum entre deux matchs d’une équipe
          </span>
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
          <span>
            <b>H6</b> Matchs maximum par équipe et par jour
          </span>
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

      <h4>
        <b>H7</b> Équipes incompatibles (ne jouent jamais en même temps)
      </h4>
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
        Indisponibilités (H3, H4) et quotas par créneau (H8, H9) : dans la section « Disponibilités
        et quotas ».
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
                  <b>{c.id}</b> {c.label}
                  <div className="muted small">{c.help}</div>
                </td>
                <td className="weight">
                  <input
                    type="range"
                    min={0}
                    max={10}
                    value={value}
                    aria-label={`Poids ${c.id}`}
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
