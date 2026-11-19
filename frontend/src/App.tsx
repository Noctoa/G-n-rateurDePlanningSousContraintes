import { useEffect, useRef, useState } from 'react'
import {
  api,
  FINAL_STATUSES,
  type JobView,
  type Tournament,
  type ValidationReport,
  type SavedTournament,
  type SavedSchedule,
} from './api/client.ts'
import { AvailabilityGrid } from './components/AvailabilityGrid.tsx'
import { FieldsEditor } from './components/FieldsEditor.tsx'
import { ResultPanel } from './components/ResultPanel.tsx'
import { HardRulesEditor, SoftWeightsEditor } from './components/RulesEditor.tsx'
import { Section } from './components/Section.tsx'
import { ScheduleView } from './components/ScheduleView.tsx'
import { SlotsEditor } from './components/SlotsEditor.tsx'
import { TeamsEditor } from './components/TeamsEditor.tsx'
import { ValidationPanel } from './components/ValidationPanel.tsx'
import { TournamentLibrary, ScheduleHistory } from './components/TournamentLibrary.tsx'
import { EXAMPLES } from './data/examples.ts'
import { download, slug } from './lib/download.ts'
import { emptyTournament, normalize, toExportJson } from './lib/tournament.ts'

const DRAFT_KEY = 'planning:draft'
const SELECTION_KEY = 'planning:selection'

type Selection = { id: string; snapshot: string }

function loadSelection(): Selection | null {
  try {
    const raw = localStorage.getItem(SELECTION_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as Selection
    return typeof value.id === 'string' && typeof value.snapshot === 'string' ? value : null
  } catch {
    return null
  }
}

function loadDraft(): Tournament {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (raw) return normalize(JSON.parse(raw) as Tournament)
  } catch {
    // stockage indisponible ou brouillon corrompu : on repart d'un exemple
  }
  return normalize(EXAMPLES[0].tournament)
}

function App() {
  const [tournament, setTournament] = useState<Tournament>(loadDraft)
  const [validationResult, setValidationResult] = useState<{
    input: Tournament
    report: ValidationReport
  } | null>(null)
  const validation = validationResult?.input === tournament ? validationResult.report : null
  const [validating, setValidating] = useState(false)
  const [backendError, setBackendError] = useState<string | null>(null)
  const [job, setJob] = useState<JobView | null>(null)
  const [jobTournament, setJobTournament] = useState<Tournament | null>(null)
  const [timeout, setTimeoutSeconds] = useState(10)
  const [selection, setSelection] = useState<Selection | null>(loadSelection)
  const [tournaments, setTournaments] = useState<SavedTournament[]>([])
  const [historyResult, setHistoryResult] = useState<{
    id: string
    version: number
    items: SavedSchedule[]
  } | null>(null)
  const [libraryLoading, setLibraryLoading] = useState(true)
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [libraryVersion, setLibraryVersion] = useState(0)
  const fileInput = useRef<HTMLInputElement>(null)
  const polling = useRef<AbortController | null>(null)
  const dirty = selection !== null && selection.snapshot !== JSON.stringify(tournament)

  useEffect(() => {
    try {
      if (selection) localStorage.setItem(SELECTION_KEY, JSON.stringify(selection))
      else localStorage.removeItem(SELECTION_KEY)
    } catch {
      /* Le brouillon reste utilisable sans stockage local. */
    }
  }, [selection])

  useEffect(() => {
    let active = true
    api
      .listTournaments()
      .then((items) => {
        if (active) {
          setTournaments(items)
          setLibraryError(null)
        }
      })
      .catch((error: unknown) => {
        if (active) setLibraryError(error instanceof Error ? error.message : String(error))
      })
      .finally(() => {
        if (active) setLibraryLoading(false)
      })
    return () => {
      active = false
    }
  }, [libraryVersion])

  const selectedId = selection?.id ?? null
  const historyCurrent =
    historyResult?.id === selectedId && historyResult?.version === libraryVersion
  const history = historyCurrent ? historyResult!.items : []
  const historyLoading = Boolean(selectedId && !historyCurrent)
  useEffect(() => {
    let active = true
    if (!selectedId) return
    api
      .listSchedules(selectedId)
      .then((items) => {
        if (active) setHistoryResult({ id: selectedId, version: libraryVersion, items })
      })
      .catch((error: unknown) => {
        if (active) {
          setLibraryError(error instanceof Error ? error.message : String(error))
          setHistoryResult({ id: selectedId, version: libraryVersion, items: [] })
        }
      })
    return () => {
      active = false
    }
  }, [selectedId, libraryVersion])

  useEffect(() => () => polling.current?.abort(), [])

  // Brouillon local + validation côté serveur (avec un léger délai pendant la saisie).
  useEffect(() => {
    let active = true
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
          if (!active) return
          setValidationResult({ input: tournament, report })
          setBackendError(null)
        })
        .catch((e: unknown) => {
          if (active) setBackendError(e instanceof Error ? e.message : String(e))
        })
        .finally(() => {
          if (active) setValidating(false)
        })
    }, 350)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [tournament])

  const running = job?.status === 'pending' || job?.status === 'running'
  const busy = running || saving || submitting

  function confirmSwitch() {
    return (
      !dirty ||
      window.confirm(
        'Des modifications ne sont pas enregistrées. Quitter ce tournoi ? Le brouillon actuel sera remplacé.',
      )
    )
  }

  async function save() {
    const snapshot = tournament
    setSaving(true)
    setLibraryError(null)
    try {
      const saved = await api.saveTournament(snapshot, selectedId ?? undefined)
      setSelection({ id: saved.id, snapshot: JSON.stringify(snapshot) })
      setLibraryVersion((value) => value + 1)
    } catch (error) {
      setLibraryError(error instanceof Error ? error.message : String(error))
    } finally {
      setSaving(false)
    }
  }

  async function follow(jobId: string, controller: AbortController) {
    await api.waitForSchedule(jobId, { signal: controller.signal, onUpdate: setJob })
    if (!controller.signal.aborted) setLibraryVersion((value) => value + 1)
  }

  async function openTournament(id: string) {
    if (!confirmSwitch()) return
    setSaving(true)
    setLibraryError(null)
    polling.current?.abort()
    try {
      const [saved, schedules] = await Promise.all([api.getTournament(id), api.listSchedules(id)])
      const snapshot = normalize(saved.tournament)
      setTournament(snapshot)
      setSelection({ id, snapshot: JSON.stringify(snapshot) })
      setHistoryResult({ id, version: libraryVersion, items: schedules })
      const latest = schedules[0]
      if (latest) openSchedule(latest)
      else {
        setJob(null)
        setJobTournament(null)
      }
    } catch (error) {
      setLibraryError(error instanceof Error ? error.message : String(error))
    } finally {
      setSaving(false)
    }
  }

  async function deleteTournament(id: string) {
    const item = tournaments.find((value) => value.id === id)
    if (
      !window.confirm(
        `Supprimer « ${item?.tournament.name ?? 'ce tournoi'} » et tout son historique ?`,
      )
    )
      return
    setSaving(true)
    setLibraryError(null)
    try {
      await api.deleteTournament(id)
      if (selectedId === id) {
        polling.current?.abort()
        setSelection(null)
        setJob(null)
        setJobTournament(null)
      }
      setLibraryVersion((value) => value + 1)
    } catch (error) {
      setLibraryError(error instanceof Error ? error.message : String(error))
    } finally {
      setSaving(false)
    }
  }

  function openSchedule(schedule: SavedSchedule) {
    polling.current?.abort()
    setJob(schedule)
    setJobTournament(schedule.tournament)
    setTimeoutSeconds(schedule.timeout_seconds)
    if (!FINAL_STATUSES.has(schedule.status)) {
      const controller = new AbortController()
      polling.current = controller
      void follow(schedule.job_id, controller).catch((error: unknown) => {
        if (!controller.signal.aborted)
          setLibraryError(error instanceof Error ? error.message : String(error))
      })
    }
  }

  async function generate() {
    polling.current?.abort()
    const controller = new AbortController()
    polling.current = controller
    const snapshot = tournament
    setSubmitting(true)
    setLibraryError(null)
    setJob(null)
    setJobTournament(snapshot)
    try {
      const created = await api.createSchedule(snapshot, timeout, selectedId ?? undefined)
      setSelection({ id: created.tournament_id, snapshot: JSON.stringify(snapshot) })
      setLibraryVersion((value) => value + 1)
      await follow(created.job_id, controller)
    } catch (e) {
      if (!controller.signal.aborted) {
        setBackendError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      setSubmitting(false)
    }
  }

  async function cancel() {
    try {
      if (job) setJob(await api.cancelSchedule(job.job_id))
    } catch (error) {
      setLibraryError(error instanceof Error ? error.message : String(error))
    }
  }

  function load(t: Tournament) {
    if (!confirmSwitch()) return
    polling.current?.abort()
    setTournament(normalize(t))
    setSelection(null)
    setJob(null)
    setJobTournament(null)
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
            disabled={busy}
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
          <button disabled={busy} onClick={() => fileInput.current?.click()}>
            Importer JSON
          </button>
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
            onClick={() =>
              download(
                `${slug(tournament.name)}.json`,
                toExportJson(tournament),
                'application/json',
              )
            }
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
          <TournamentLibrary
            tournaments={tournaments}
            selectedId={selectedId}
            loading={libraryLoading}
            busy={busy}
            dirty={dirty}
            error={libraryError}
            canSave={Boolean(validation?.valid) && !validating}
            onSave={() => void save()}
            onOpen={(id) => void openTournament(id)}
            onDelete={(id) => void deleteTournament(id)}
            onRefresh={() => setLibraryVersion((value) => value + 1)}
          />
          <section className="panel">
            <h2>Vérification</h2>
            <ValidationPanel
              report={validation}
              loading={validating || (!validation && !backendError)}
              error={backendError}
            />
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
                disabled={busy || validating || !validation?.valid}
                onClick={() => void generate()}
              >
                Générer le planning
              </button>
              {running && <button onClick={() => void cancel()}>Annuler</button>}
            </div>
            {job && <ResultPanel job={job} />}
          </section>
          {selectedId && (
            <ScheduleHistory
              schedules={history}
              selectedJobId={job?.job_id}
              loading={historyLoading}
              disabled={busy}
              onOpen={openSchedule}
            />
          )}
        </aside>
      </main>

      {job && !running && jobTournament && (
        <section className="panel wide" id="resultat">
          <h2>{job.schedule ? `Planning — ${jobTournament.name}` : 'Diagnostic'}</h2>
          <ScheduleView key={job.job_id} job={job} tournament={jobTournament} />
        </section>
      )}
    </div>
  )
}

export default App
