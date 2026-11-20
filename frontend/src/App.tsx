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
type View = 'setup' | 'rules' | 'schedule' | 'library'

const STEPS = [
  { id: 'setup', title: 'Tournoi', detail: 'Équipes, terrains et horaires' },
  { id: 'rules', title: 'Contraintes', detail: 'Disponibilités et règles' },
  { id: 'schedule', title: 'Planning', detail: 'Génération et résultats' },
] as const

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
  const [view, setView] = useState<View>('setup')
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

  function navigate(next: View) {
    setView(next)
    window.scrollTo({ top: 0, behavior: 'instant' })
    requestAnimationFrame(() => document.getElementById(`view-title-${next}`)?.focus())
  }

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
        navigate('setup')
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
    navigate('schedule')
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

  async function generate(timeoutSeconds = timeout) {
    navigate('schedule')
    polling.current?.abort()
    const controller = new AbortController()
    polling.current = controller
    const snapshot = tournament
    setSubmitting(true)
    setLibraryError(null)
    setJob(null)
    setJobTournament(snapshot)
    try {
      const created = await api.createSchedule(snapshot, timeoutSeconds, selectedId ?? undefined)
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
    navigate('setup')
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

  const canSave = Boolean(validation?.valid) && !validating
  const currentGeneration =
    jobTournament &&
    JSON.stringify(normalize(jobTournament)) === JSON.stringify(normalize(tournament))
      ? job
      : null
  const verifiedSchedule = job?.status === 'solved' && job.schedule && job.violations.length === 0
  const retryTimeout = Math.min(60, Math.max(timeout, (job?.timeout_seconds ?? timeout) * 3))
  const saveLabel = saving ? 'Enregistrement…' : 'Enregistrer'
  const saveStatus = dirty
    ? 'Modifications non enregistrées'
    : selectedId
      ? 'Tournoi enregistré'
      : 'Brouillon sur cet appareil'

  return (
    <div className="app">
      <header className="topbar">
        <div className="tournament-heading">
          <p className="eyebrow">Planificateur de tournoi</p>
          <label className="title-label">
            <span className="sr-only">Nom du tournoi</span>
            <input
              className="title-input"
              value={tournament.name}
              onChange={(e) => setTournament({ ...tournament, name: e.target.value })}
            />
          </label>
          <span className={`save-status${dirty ? ' unsaved' : ''}`} role="status">
            <span aria-hidden="true">●</span> {saveStatus}
          </span>
        </div>
        <div className="toolbar">
          <button
            className={view === 'library' ? 'active-button' : ''}
            onClick={() => navigate(view === 'library' ? 'setup' : 'library')}
            aria-pressed={view === 'library'}
          >
            Mes tournois
          </button>
          <button disabled={busy} onClick={() => load(emptyTournament())}>
            Nouveau tournoi
          </button>
          <button disabled={busy || !canSave} onClick={() => void save()}>
            {saveLabel}
          </button>
        </div>
      </header>

      <nav className="steps" aria-label="Étapes du tournoi">
        {STEPS.map((step, index) => (
          <button
            key={step.id}
            className={`step${view === step.id ? ' current' : ''}`}
            aria-current={view === step.id ? 'step' : undefined}
            onClick={() => navigate(step.id)}
          >
            <span className="step-number" aria-hidden="true">
              {index + 1}
            </span>
            <span>
              <strong>{step.title}</strong>
              <span className="step-description">{step.detail}</span>
            </span>
          </button>
        ))}
      </nav>

      {libraryError && (
        <p className="status error" role="alert">
          {libraryError}
        </p>
      )}

      <main
        className={`workspace-shell${view === 'schedule' || view === 'library' ? ' full-width' : ''}`}
      >
        <div className="workspace-content">
          <section hidden={view !== 'setup'} aria-labelledby="view-title-setup">
            <div className="page-heading">
              <p className="eyebrow">Étape 1 sur 3</p>
              <h1 id="view-title-setup" tabIndex={-1}>
                Préparez votre tournoi
              </h1>
              <p className="muted">
                Ajoutez les participants et choisissez où et quand les matchs auront lieu.
              </p>
            </div>
            <div className="editor">
              <Section
                title="Informations générales"
                description="Le format et la description de votre tournoi."
              >
                <label className="field">
                  <span>
                    Description <span className="muted">(facultatif)</span>
                  </span>
                  <textarea
                    rows={2}
                    placeholder="Ex. Tournoi de fin de saison du club"
                    value={tournament.description ?? ''}
                    onChange={(e) =>
                      setTournament({ ...tournament, description: e.target.value || null })
                    }
                  />
                </label>
                <label className="field">
                  <span>Format des rencontres</span>
                  <select
                    value={tournament.format ?? 'round_robin'}
                    onChange={(e) =>
                      setTournament({
                        ...tournament,
                        format: e.target.value as Tournament['format'],
                      })
                    }
                  >
                    <option value="round_robin">
                      Aller simple — chaque équipe rencontre les autres une fois
                    </option>
                    <option value="double_round_robin">
                      Aller-retour — deux rencontres par paire d’équipes
                    </option>
                  </select>
                </label>
              </Section>
              <Section
                title="Équipes"
                hint={`${tournament.teams.length} équipes`}
                description="Les participants au tournoi, regroupés en poules si besoin."
              >
                <TeamsEditor tournament={tournament} onChange={setTournament} />
              </Section>
              <Section
                title="Terrains"
                hint={`${tournament.fields.length} terrains`}
                description="Les lieux disponibles pour accueillir les matchs."
                defaultOpen={false}
              >
                <FieldsEditor tournament={tournament} onChange={setTournament} />
              </Section>
              <Section
                title="Dates et horaires"
                hint={`${tournament.slots.length} créneaux`}
                description="Les jours de jeu, les heures de début et la durée d’un match."
                defaultOpen={false}
              >
                <SlotsEditor tournament={tournament} onChange={setTournament} />
              </Section>
              <Section
                title="Exemples et fichiers"
                description="Partir d’un exemple ou importer un tournoi au format JSON."
                defaultOpen={false}
              >
                <div className="row wrap">
                  <select
                    value=""
                    disabled={busy}
                    aria-label="Charger un exemple"
                    onChange={(e) => {
                      const example = EXAMPLES.find((x) => x.key === e.target.value)
                      if (example) load(example.tournament)
                    }}
                  >
                    <option value="" disabled>
                      Choisir un exemple…
                    </option>
                    {EXAMPLES.map((example) => (
                      <option key={example.key} value={example.key}>
                        {example.label}
                      </option>
                    ))}
                  </select>
                  <button disabled={busy} onClick={() => fileInput.current?.click()}>
                    Importer JSON
                  </button>
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
              </Section>
            </div>
            <div className="step-footer">
              <p className="muted small">Vos saisies sont conservées dans un brouillon local.</p>
              <button className="primary" onClick={() => navigate('rules')}>
                Continuer vers les contraintes <span aria-hidden="true">→</span>
              </button>
            </div>
          </section>

          <section hidden={view !== 'rules'} aria-labelledby="view-title-rules">
            <div className="page-heading">
              <p className="eyebrow">Étape 2 sur 3</p>
              <h1 id="view-title-rules" tabIndex={-1}>
                Définissez vos contraintes
              </h1>
              <p className="muted">
                Précisez les indisponibilités et le rythme de jeu. Les valeurs actuelles sont déjà
                utilisables.
              </p>
            </div>
            <div className="editor">
              <Section
                title="Rythme des matchs"
                description="Le repos entre deux rencontres et les limites par équipe."
              >
                <HardRulesEditor tournament={tournament} onChange={setTournament} />
              </Section>
              <Section
                title="Disponibilités"
                description="Choisissez une équipe ou un terrain, puis cliquez sur les horaires à modifier."
                defaultOpen={false}
              >
                <AvailabilityGrid tournament={tournament} onChange={setTournament} />
              </Section>
              <Section
                title="Préférences avancées"
                description="L’importance des horaires préférés et de l’équilibre du planning."
                defaultOpen={false}
              >
                <SoftWeightsEditor tournament={tournament} onChange={setTournament} />
              </Section>
            </div>
            <div className="step-footer">
              <button onClick={() => navigate('setup')}>← Retour au tournoi</button>
              <button className="primary" onClick={() => navigate('schedule')}>
                Continuer vers le planning <span aria-hidden="true">→</span>
              </button>
            </div>
          </section>

          <section hidden={view !== 'schedule'} aria-labelledby="view-title-schedule">
            <div className="page-heading">
              <p className="eyebrow">Étape 3 sur 3</p>
              <h1 id="view-title-schedule" tabIndex={-1}>
                Votre planning
              </h1>
              <p className="muted">
                Générez les rencontres, consultez le programme de chaque équipe et exportez le
                résultat.
              </p>
            </div>
            <section className="panel generation-bar" aria-label="Générer le planning">
              <div>
                <h2>
                  {running || submitting
                    ? 'Génération en cours…'
                    : 'Prêt à organiser les rencontres ?'}
                </h2>
                <p className="muted small">
                  Le tournoi et chaque résultat sont enregistrés automatiquement.
                </p>
              </div>
              <div className="generation-actions">
                <label className="field inline">
                  <span>Temps maximum</span>
                  <input
                    type="number"
                    min={1}
                    max={60}
                    aria-label="Temps maximum"
                    value={timeout}
                    onChange={(e) =>
                      setTimeoutSeconds(Math.min(60, Math.max(1, Number(e.target.value))))
                    }
                  />
                  <span className="muted">s</span>
                </label>
                <button
                  className="primary"
                  disabled={busy || !canSave}
                  onClick={() => void generate()}
                >
                  {running || submitting ? 'Génération…' : 'Générer le planning'}
                </button>
                {running && <button onClick={() => void cancel()}>Annuler</button>}
              </div>
            </section>
            {(!validation?.valid || backendError) && (
              <section className="panel generation-validation">
                <ValidationPanel
                  report={validation}
                  loading={validating || (!validation && !backendError)}
                  error={backendError}
                  generation={currentGeneration}
                />
                <button onClick={() => navigate('setup')}>Revenir à la préparation</button>
              </section>
            )}
            {running && (
              <div className="planning-empty" role="status">
                <span className="loading-ring" aria-hidden="true" />
                <h2>Recherche d’un planning</h2>
                <p className="muted">Les matchs sont placés en respectant vos contraintes.</p>
              </div>
            )}
            {!job && !submitting && (
              <div className="planning-empty">
                <span className="empty-calendar" aria-hidden="true">
                  ▦
                </span>
                <h2>Le planning apparaîtra ici</h2>
                <p className="muted">
                  Lancez la génération pour répartir vos {validation?.summary?.matches ?? ''} matchs
                  entre les terrains et les horaires.
                </p>
              </div>
            )}
            {job && !running && jobTournament && (
              <section className="panel schedule-result" id="resultat">
                <div className="result-heading">
                  <div>
                    <p className="eyebrow">
                      {job.schedule ? 'Planning généré' : 'Résultat de la recherche'}
                    </p>
                    <h2>{jobTournament.name}</h2>
                  </div>
                  <span className={`result-badge ${verifiedSchedule ? 'success' : 'attention'}`}>
                    {verifiedSchedule
                      ? 'Toutes les contraintes respectées'
                      : job.status === 'timeout'
                        ? 'Temps de recherche dépassé'
                        : 'Consulter le diagnostic'}
                  </span>
                </div>
                <ScheduleView key={job.job_id} job={job} tournament={jobTournament} />
                {job.status === 'timeout' && (
                  <div className="result-actions">
                    <button
                      className="primary"
                      disabled={busy || !canSave}
                      onClick={() => {
                        setTimeoutSeconds(retryTimeout)
                        void generate(retryTimeout)
                      }}
                    >
                      Réessayer avec {retryTimeout} s
                    </button>
                    <button onClick={() => navigate('rules')}>Revoir les contraintes</button>
                  </div>
                )}
              </section>
            )}
            {selectedId && (
              <div className="history-section">
                <Section
                  title="Historique des générations"
                  hint={`${history.length} résultats`}
                  description="Rouvrir un ancien planning avec ses données d’origine."
                  defaultOpen={false}
                >
                  <ScheduleHistory
                    schedules={history}
                    selectedJobId={job?.job_id}
                    loading={historyLoading}
                    disabled={busy}
                    onOpen={openSchedule}
                  />
                </Section>
              </div>
            )}
          </section>

          <section hidden={view !== 'library'} aria-labelledby="view-title-library">
            <div className="page-heading">
              <p className="eyebrow">Bibliothèque</p>
              <h1 id="view-title-library" tabIndex={-1}>
                Mes tournois
              </h1>
              <p className="muted">
                Ouvrez un tournoi pour reprendre sa préparation ou retrouver ses plannings.
              </p>
            </div>
            <TournamentLibrary
              tournaments={tournaments}
              selectedId={selectedId}
              loading={libraryLoading}
              busy={busy}
              onOpen={(id) => void openTournament(id)}
              onDelete={(id) => void deleteTournament(id)}
              onRefresh={() => setLibraryVersion((value) => value + 1)}
            />
            <div className="step-footer">
              <button onClick={() => navigate('setup')}>← Revenir au tournoi actuel</button>
              <button className="primary" disabled={busy} onClick={() => load(emptyTournament())}>
                Créer un tournoi
              </button>
            </div>
          </section>
        </div>
        <aside className="workspace-summary" hidden={view === 'schedule' || view === 'library'}>
          <section className="panel">
            <p className="eyebrow">En un coup d’œil</p>
            <h2>Votre tournoi</h2>
            <ValidationPanel
              report={validation}
              loading={validating || (!validation && !backendError)}
              error={backendError}
              generation={currentGeneration}
            />
          </section>
          <div className="guide-note">
            <span className="guide-icon" aria-hidden="true">
              i
            </span>
            <div>
              <h3>
                {view === 'setup'
                  ? 'Commencez par les équipes'
                  : 'Des règles adaptées à votre tournoi'}
              </h3>
              <p>
                {view === 'setup'
                  ? 'Les terrains et les horaires se déplient lorsque vous en avez besoin. Passez ensuite aux contraintes.'
                  : 'Les indisponibilités et les règles obligatoires seront respectées pour chaque rencontre.'}
              </p>
            </div>
          </div>
        </aside>
      </main>
    </div>
  )
}

export default App
