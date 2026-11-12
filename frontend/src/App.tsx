import { useEffect, useState } from 'react'
import { api, type Health } from './api/client'

function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  return (
    <main>
      <h1>Planning de tournoi sous contraintes</h1>
      {health && (
        <p>
          Backend : {health.status} (v{health.version})
        </p>
      )}
      {error && <p role="alert">Backend injoignable : {error}</p>}
      {!health && !error && <p>Connexion au backend…</p>}
    </main>
  )
}

export default App
