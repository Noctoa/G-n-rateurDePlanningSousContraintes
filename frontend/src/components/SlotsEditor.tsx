import { useState } from 'react'
import type { Tournament } from '../api/client.ts'
import { formatDay, nextDay } from '../lib/format.ts'
import { regenerateSlots, slotGrid, type SlotGrid } from '../lib/tournament.ts'

export function SlotsEditor({
  tournament,
  onChange,
}: {
  tournament: Tournament
  onChange: (t: Tournament) => void
}) {
  const grid = slotGrid(tournament)
  const [newTime, setNewTime] = useState('09:00')

  const apply = (patch: Partial<SlotGrid>) =>
    onChange(
      regenerateSlots(tournament, {
        days: patch.days ?? grid.days,
        times: patch.times ?? grid.times,
        durationMinutes: patch.durationMinutes ?? grid.durationMinutes,
      }),
    )

  return (
    <>
      {!grid.regular && (
        <p className="notice">
          Les créneaux importés ne forment pas une grille régulière (durées ou horaires différents
          selon les jours). Toute modification ci-dessous les régénère en grille jours × heures.
        </p>
      )}

      <div className="grid-2">
        <div>
          <h4>Jours</h4>
          <ul className="chips-list">
            {grid.days.map((day) => (
              <li key={day} className="row">
                <input
                  type="date"
                  value={day}
                  aria-label="Jour"
                  onChange={(e) =>
                    e.target.value &&
                    apply({ days: grid.days.map((d) => (d === day ? e.target.value : d)) })
                  }
                />
                <span className="muted small">{formatDay(day)}</span>
                <button
                  className="icon-button"
                  title="Retirer ce jour"
                  disabled={grid.days.length <= 1}
                  onClick={() => apply({ days: grid.days.filter((d) => d !== day) })}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
          <button onClick={() => apply({ days: [...grid.days, nextDay(grid.days.at(-1))] })}>
            Ajouter un jour
          </button>
        </div>

        <div>
          <h4>Heures de début</h4>
          <div className="chips">
            {grid.times.map((time) => (
              <span key={time} className="chip">
                {time}
                <button
                  className="chip-remove"
                  title="Retirer cette heure"
                  disabled={grid.times.length <= 1}
                  onClick={() => apply({ times: grid.times.filter((x) => x !== time) })}
                >
                  ✕
                </button>
              </span>
            ))}
          </div>
          <div className="row">
            <input
              type="time"
              step={300}
              value={newTime}
              aria-label="Nouvelle heure"
              onChange={(e) => setNewTime(e.target.value)}
            />
            <button
              disabled={!newTime || grid.times.includes(newTime)}
              onClick={() => apply({ times: [...grid.times, newTime] })}
            >
              Ajouter l’heure
            </button>
          </div>

          <label className="field inline">
            <span>Durée d’un match</span>
            <input
              type="number"
              min={5}
              max={600}
              step={5}
              value={grid.durationMinutes}
              onChange={(e) => {
                const value = Number(e.target.value)
                if (value > 0) apply({ durationMinutes: value })
              }}
            />
            <span className="muted">min</span>
          </label>
        </div>
      </div>

      <p className="muted small">
        {tournament.slots.length} créneaux ({grid.days.length} jour(s) × {grid.times.length}{' '}
        heure(s)).
      </p>
    </>
  )
}
