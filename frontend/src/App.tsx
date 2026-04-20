import { useCallback, useEffect, useRef, useState } from 'react'
import { apiUrl, fetchHealth } from './api'
import { Chat } from './components/Chat'
import { DocumentList } from './components/DocumentList'
import { HandbookView } from './components/HandbookView'
import { Uploader } from './components/Uploader'

function App() {
  const [health, setHealth] = useState<string>('…')
  const [error, setError] = useState<string | null>(null)
  const [docRefresh, setDocRefresh] = useState(0)
  const [handbookTopic, setHandbookTopic] = useState('')
  const [handbookFlash, setHandbookFlash] = useState(false)
  const handbookRef = useRef<HTMLElement>(null)

  useEffect(() => {
    fetchHealth()
      .then((h) => setHealth(h.status))
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : 'Health check failed'),
      )
  }, [])

  const onHandbookRedirect = useCallback((topic: string) => {
    setHandbookTopic(topic)
    setHandbookFlash(true)
    window.setTimeout(() => setHandbookFlash(false), 2400)
    window.setTimeout(() => {
      handbookRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }, 100)
  }, [])

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-950 text-slate-100">
      <header className="shrink-0 border-b border-slate-800 px-4 py-3">
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
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-slate-800 md:grid-cols-3 md:grid-rows-1">
        <section className="flex min-h-[280px] flex-col overflow-hidden bg-slate-950 p-4 md:h-full md:min-h-0">
          <h2 className="mb-3 shrink-0 text-sm font-medium uppercase tracking-wide text-slate-500">
            Documents
          </h2>
          <div className="shrink-0">
            <Uploader onUploaded={() => setDocRefresh((v) => v + 1)} />
          </div>
          <div className="mt-4 flex min-h-0 flex-1 flex-col border-t border-slate-800 pt-4">
            <DocumentList refreshVersion={docRefresh} />
          </div>
        </section>
        <section className="flex min-h-[320px] flex-col overflow-hidden bg-slate-950 p-4 md:h-full md:min-h-0">
          <h2 className="mb-3 shrink-0 text-sm font-medium uppercase tracking-wide text-slate-500">
            Chat
          </h2>
          <div className="flex min-h-0 flex-1 flex-col">
            <Chat onHandbookRedirect={onHandbookRedirect} />
          </div>
        </section>
        <section
          ref={handbookRef}
          className={`flex min-h-[320px] flex-col overflow-y-auto overflow-x-hidden bg-slate-950 p-4 transition-shadow md:h-full md:min-h-0 ${
            handbookFlash ? 'ring-2 ring-sky-500 ring-offset-2 ring-offset-slate-950' : ''
          }`}
        >
          <h2 className="mb-3 shrink-0 text-sm font-medium uppercase tracking-wide text-slate-500">
            Handbook
          </h2>
          <div className="flex min-h-0 flex-1 flex-col">
            <HandbookView topic={handbookTopic} onTopicChange={setHandbookTopic} />
          </div>
        </section>
      </div>
    </div>
  )
}

export default App
