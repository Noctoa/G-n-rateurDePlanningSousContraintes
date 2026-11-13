import type { Tournament } from '../api/client.ts'
import { addField, removeField, updateField } from '../lib/tournament.ts'

export function FieldsEditor({
  tournament,
  onChange,
}: {
  tournament: Tournament
  onChange: (t: Tournament) => void
}) {
  return (
    <>
      <ul className="chips-list">
        {tournament.fields.map((f) => (
          <li key={f.id} className="row">
            <span className="tag">{f.id}</span>
            <input
              value={f.name}
              aria-label={`Nom du terrain ${f.id}`}
              onChange={(e) => onChange(updateField(tournament, f.id, { name: e.target.value }))}
            />
            <button
              className="icon-button"
              title="Supprimer le terrain"
              disabled={tournament.fields.length <= 1}
              onClick={() => onChange(removeField(tournament, f.id))}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
      <button onClick={() => onChange(addField(tournament))}>Ajouter un terrain</button>
    </>
  )
}
