import { useEffect, useState } from 'react'
import { apiUrl, fetchHealth } from './api'

function App() {
  const [health, setHealth] = useState<string>('…')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchHealth()
      .then((h) => setHealth(h.status))
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : 'Health check failed'),
      )
  }, [])

  return (
    <div className="flex min-h-screen flex-col bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-4 py-3">
        <h1 className="text-lg font-semibold tracking-tight">
          Handbook Generator
        </h1>
        <p className="text-sm text-slate-400">
          API:{' '}
          <code className="rounded bg-slate-900 px-1.5 py-0.5 text-xs">
            {apiUrl('/')}
          </code>
          {' · '}
          <span className="text-emerald-400">
            {error ? `error: ${error}` : `health: ${health}`}
          </span>
        </p>
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-slate-800 md:grid-cols-3">
        <section className="flex min-h-[200px] flex-col bg-slate-950 p-4">
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-slate-500">
            Documents
          </h2>
          <p className="text-sm text-slate-400">
            PDF upload and document list will appear here.
          </p>
        </section>
        <section className="flex min-h-[200px] flex-col bg-slate-950 p-4">
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-slate-500">
            Chat
          </h2>
          <p className="text-sm text-slate-400">
            RAG chat will appear here.
          </p>
        </section>
        <section className="flex min-h-[200px] flex-col bg-slate-950 p-4">
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-slate-500">
            Handbook
          </h2>
          <p className="text-sm text-slate-400">
            Long-form handbook generation will appear here.
          </p>
        </section>
      </div>
    </div>
  )
}

export default App
