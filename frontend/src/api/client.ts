// Client HTTP typé vers le backend FastAPI.
// Les types reflètent le contrat OpenAPI exposé par le backend (http://localhost:8000/docs).
// En dev, Vite proxifie /api vers http://localhost:8000 (voir vite.config.ts).

// --- Tournoi (entrée) -------------------------------------------------------------------

export interface Team {
  id: string
  name: string
  pool?: string | null
  unavailable_slots?: string[]
  preferred_slots?: string[]
}

export interface Venue {
  id: string
  name: string
  unavailable_slots?: string[]
}

export interface Slot {
  id: string
  day: string // AAAA-MM-JJ
  start: string // HH:MM
  duration_minutes: number
  min_matches?: number
  max_matches?: number | null
}

export interface Incompatibility {
  teams: [string, string]
  reason?: string | null
}

export interface Rules {
  min_rest_minutes?: number
  max_matches_per_team_per_day?: number | null
}

export type TournamentFormat = 'round_robin' | 'double_round_robin'

export type SoftConstraintId = 'S1' | 'S2' | 'S3' | 'S4' | 'S5'

export interface Tournament {
  $schema?: string
  name: string
  description?: string | null
  format?: TournamentFormat
  teams: Team[]
  fields: Venue[]
  slots: Slot[]
  incompatibilities?: Incompatibility[]
  rules?: Rules
  /** Poids des contraintes souples ; les absents prennent leur valeur par défaut. */
  weights?: Partial<Record<SoftConstraintId, number>>
}

// --- Résultats --------------------------------------------------------------------------

export type HardConstraintId = 'H1' | 'H2' | 'H3' | 'H4' | 'H5' | 'H6' | 'H7' | 'H8' | 'H9'

export interface Match {
  id: string
  home: string
  away: string
  round: number
  leg: number
  pool: string | null
}

export interface Assignment {
  match_id: string
  slot_id: string
  field_id: string
}

export interface Schedule {
  assignments: Assignment[]
}

export interface ConstraintRef {
  id: HardConstraintId
  label: string
}

export interface Conflict {
  source: 'precheck' | 'search'
  constraints: ConstraintRef[]
  explanation: string
  suggestions: string[]
}

export interface Diagnosis {
  feasibility: 'feasible' | 'infeasible' | 'unknown'
  summary: string
  conflicts: Conflict[]
  minimal: boolean | null
}

export interface Violation {
  constraint: HardConstraintId | null
  message: string
  matches: string[]
  slots: string[]
}

export interface SearchStats {
  nodes: number
  backtracks: number
  max_depth: number
  elapsed_ms: number
}

export type JobStatus =
  'pending' | 'running' | 'solved' | 'infeasible' | 'timeout' | 'cancelled' | 'error'

export const FINAL_STATUSES: ReadonlySet<JobStatus> = new Set([
  'solved',
  'infeasible',
  'timeout',
  'cancelled',
  'error',
])

export interface JobCreated {
  job_id: string
  status: JobStatus
}

export interface JobView {
  job_id: string
  status: JobStatus
  tournament_name: string
  timeout_seconds: number
  created_at: string
  started_at: string | null
  finished_at: string | null
  matches: Match[]
  schedule: Schedule | null
  stats: SearchStats | null
  diagnosis: Diagnosis | null
  violations: Violation[]
  error: string | null
}

export interface InputError {
  location: string
  message: string
}

export interface ValidationReport {
  valid: boolean
  errors: InputError[]
  summary: {
    teams: number
    fields: number
    slots: number
    matches: number
    places: number
  } | null
  warnings: Conflict[]
}

export interface Health {
  status: string
  version: string
}

// --- Transport --------------------------------------------------------------------------

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const BASE_URL: string = import.meta.env.VITE_API_URL ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    throw new ApiError(response.status, await response.text())
  }
  return (await response.json()) as T
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export const api = {
  health: () => request<Health>('/health'),

  validateTournament: (tournament: unknown) =>
    request<ValidationReport>('/tournaments/validate', {
      method: 'POST',
      body: JSON.stringify(tournament),
    }),

  createSchedule: (tournament: Tournament, timeoutSeconds = 10) =>
    request<JobCreated>('/schedules', {
      method: 'POST',
      body: JSON.stringify({ tournament, timeout_seconds: timeoutSeconds }),
    }),

  getSchedule: (jobId: string) => request<JobView>(`/schedules/${jobId}`),

  cancelSchedule: (jobId: string) => request<JobView>(`/schedules/${jobId}`, { method: 'DELETE' }),

  /** Interroge le job jusqu'à un statut final. `onUpdate` reçoit chaque état intermédiaire. */
  async waitForSchedule(
    jobId: string,
    {
      intervalMs = 300,
      signal,
      onUpdate,
    }: {
      intervalMs?: number
      signal?: AbortSignal
      onUpdate?: (job: JobView) => void
    } = {},
  ): Promise<JobView> {
    for (;;) {
      const job = await api.getSchedule(jobId)
      onUpdate?.(job)
      if (FINAL_STATUSES.has(job.status)) return job
      if (signal?.aborted) throw new DOMException('Attente annulée', 'AbortError')
      await sleep(intervalMs)
    }
  },
}
