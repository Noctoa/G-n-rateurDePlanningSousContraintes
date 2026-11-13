import { useEffect, useRef, useState } from 'react'
import { api, type JobView, type Tournament, type ValidationReport } from './api/client.ts'
import { AvailabilityGrid } from './components/AvailabilityGrid.tsx'
import { FieldsEditor } from './components/FieldsEditor.tsx'
import { ResultPanel, ScheduleTable } from './components/ResultPanel.tsx'
import { HardRulesEditor, SoftWeightsEditor } from './components/RulesEditor.tsx'
import { Section } from './components/Section.tsx'
import { SlotsEditor } from './components/SlotsEditor.tsx'
import { TeamsEditor } from './components/TeamsEditor.tsx'
import { ValidationPanel } from './components/ValidationPanel.tsx'
import { EXAMPLES } from './data/examples.ts'
import { emptyTournament, normalize, toExportJson } from './lib/tournament.ts'

const DRAFT_KEY = 'planning:draft'

function loadDraft(): Tournament {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (raw) return normalize(JSON.parse(raw) as Tournament)
  } catch {
    // stockage indisponible ou brouillon corrompu : on repart d'un exemple
  }
  return normalize(EXAMPLES[0].tournament)
}

function download(filename: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: 'application/json' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  a.click()
  URL.revokeObjectURL(url)
}

function slug(name: string): string {
  return (
    name
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '') || 'tournoi'
  )
}

function App() {
  const [tournament, setTournament] = useState<Tournament>(loadDraft)
  const [validation, setValidation] = useState<ValidationReport | null>(null)
  const [validating, setValidating] = useState(false)
  const [backendError, setBackendError] = useState<string | null>(null)
  const [job, setJob] = useState<JobView | null>(null)
  const [jobTournament, setJobTournament] = useState<Tournament | null>(null)
  const [timeout, setTimeoutSeconds] = useState(10)
  const fileInput = useRef<HTMLInputElement>(null)
  const polling = useRef<AbortController | null>(null)

  // Brouillon local + validation côté serveur (avec un léger délai pendant la saisie).
  useEffect(() => {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(tournament))
    } catch {
      // stockage plein ou désactivé : sans conséquence
    }
    const timer = setTimeout(() => {
      setValidating(true)
      api
        .validateTournament(tournament)
        .then((report) => {
          setValidation(report)
          setBackendError(null)
        })
        .catch((e: unknown) => setBackendError(e instanceof Error ? e.message : String(e)))
        .finally(() => setValidating(false))
    }, 350)
    return () => clearTimeout(timer)
  }, [tournament])

  const running = job?.status === 'pending' || job?.status === 'running'

  async function generate() {
    polling.current?.abort()
    const controller = new AbortController()
    polling.current = controller
    const snapshot = tournament
    setJobTournament(snapshot)
    try {
      const created = await api.createSchedule(snapshot, timeout)
      setJob(null)
      await api.waitForSchedule(created.job_id, { signal: controller.signal, onUpdate: setJob })
    } catch (e) {
      if (!controller.signal.aborted) {
        setBackendError(e instanceof Error ? e.message : String(e))
      }
    }
  }

  async function cancel() {
    if (job) setJob(await api.cancelSchedule(job.job_id))
  }

  function load(t: Tournament) {
    setTournament(normalize(t))
    setJob(null)
  }

  async function importFile(file: File) {
    try {
      load(JSON.parse(await file.text()) as Tournament)
    } catch {
      alert(`« ${file.name} » n’est pas un fichier JSON valide.`)
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>Planning de tournoi</h1>
          <input
            className="title-input"
            value={tournament.name}
            aria-label="Nom du tournoi"
            onChange={(e) => setTournament({ ...tournament, name: e.target.value })}
          />
        </div>
        <div className="toolbar">
          <select
            value=""
            aria-label="Charger un exemple"
            onChange={(e) => {
              const key = e.target.value
              if (key === 'new') load(emptyTournament())
              const example = EXAMPLES.find((x) => x.key === key)
              if (example) load(example.tournament)
            }}
          >
            <option value="" disabled>
              Charger…
            </option>
            <option value="new">Nouveau tournoi vide</option>
            {EXAMPLES.map((x) => (
              <option key={x.key} value={x.key}>
                Exemple : {x.label}
              </option>
            ))}
          </select>
          <button onClick={() => fileInput.current?.click()}>Importer JSON</button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void importFile(file)
              e.target.value = ''
            }}
          />
          <button
            onClick={() => download(`${slug(tournament.name)}.json`, toExportJson(tournament))}
          >
            Exporter JSON
          </button>
        </div>
      </header>

      <main className="layout">
        <div className="editor">
          <Section title="Général">
            <label className="field">
              <span>Description</span>
              <textarea
                rows={2}
                value={tournament.description ?? ''}
                onChange={(e) =>
                  setTournament({ ...tournament, description: e.target.value || null })
                }
              />
            </label>
            <label className="field inline">
              <span>Format</span>
              <select
                value={tournament.format ?? 'round_robin'}
                onChange={(e) =>
                  setTournament({
                    ...tournament,
                    format: e.target.value as Tournament['format'],
                  })
                }
              >
                <option value="round_robin">Aller simple (chacun rencontre chacun)</option>
                <option value="double_round_robin">Aller-retour</option>
              </select>
            </label>
          </Section>

          <Section title="Équipes" hint={`${tournament.teams.length}`}>
            <TeamsEditor tournament={tournament} onChange={setTournament} />
          </Section>

          <Section title="Terrains" hint={`${tournament.fields.length}`}>
            <FieldsEditor tournament={tournament} onChange={setTournament} />
          </Section>

          <Section title="Créneaux" hint={`${tournament.slots.length}`}>
            <SlotsEditor tournament={tournament} onChange={setTournament} />
          </Section>

          <Section title="Disponibilités et quotas" hint="H3 · H4 · H8 · H9 · préférences">
            <AvailabilityGrid tournament={tournament} onChange={setTournament} />
          </Section>

          <Section title="Règles obligatoires" hint="H5 · H6 · H7">
            <HardRulesEditor tournament={tournament} onChange={setTournament} />
          </Section>

          <Section title="Préférences" hint="S1 … S5" defaultOpen={false}>
            <SoftWeightsEditor tournament={tournament} onChange={setTournament} />
          </Section>
        </div>

        <aside className="sidebar">
          <section className="panel">
            <h2>Vérification</h2>
            <ValidationPanel report={validation} loading={validating} error={backendError} />
          </section>

          <section className="panel">
            <h2>Génération</h2>
            <label className="field inline">
              <span>Temps maximum</span>
              <input
                type="number"
                min={1}
                max={60}
                value={timeout}
                onChange={(e) =>
                  setTimeoutSeconds(Math.min(60, Math.max(1, Number(e.target.value))))
                }
              />
              <span className="muted">s</span>
            </label>
            <div className="row">
              <button
                className="primary"
                disabled={running || !validation?.valid}
                onClick={() => void generate()}
              >
                Générer le planning
              </button>
              {running && <button onClick={() => void cancel()}>Annuler</button>}
            </div>
            {job && <ResultPanel job={job} />}
          </section>
        </aside>
      </main>

      {job?.schedule && jobTournament && (
        <section className="panel wide">
          <h2>Planning</h2>
          <ScheduleTable job={job} tournament={jobTournament} />
        </section>
      )}
    </div>
  )
}

export default App
