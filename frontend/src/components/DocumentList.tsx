import { useCallback, useEffect, useState } from 'react'
import { deleteDocument, fetchDocuments, type Document } from '../api'

const POLL_MS = 5000

type Props = {
  refreshVersion?: number
}

function formatWhen(iso: string): string {
  try {
    const d = new Date(iso)
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(d)
  } catch {
    return iso
  }
}

export function DocumentList({ refreshVersion = 0 }: Props) {
  const [docs, setDocs] = useState<Document[]>([])
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const list = await fetchDocuments()
      setDocs(list)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load documents')
    }
  }, [])

  useEffect(() => {
    const t = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(t)
  }, [load, refreshVersion])

  useEffect(() => {
    const id = window.setInterval(() => {
      void load()
    }, POLL_MS)
    return () => window.clearInterval(id)
  }, [load])

  const onDelete = async (id: string) => {
    setDeletingId(id)
    try {
      await deleteDocument(id)
      setDocs((prev) => prev.filter((d) => d.id !== id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">
          Ingested
        </h3>
        <button
          type="button"
          onClick={() => void load()}
          className="text-xs text-sky-400 hover:text-sky-300"
        >
          Refresh
        </button>
      </div>
      {error ? (
        <p className="mb-2 rounded border border-red-900/60 bg-red-950/30 px-2 py-1.5 text-xs text-red-300">
          {error}
        </p>
      ) : null}
      {docs.length === 0 && !error ? (
        <p className="text-sm text-slate-500">No documents yet. Upload a PDF above.</p>
      ) : null}
      {docs.length > 0 ? (
        <ul className="scroll-pane min-h-0 flex-1 space-y-2 pr-1">
          {docs.map((d) => (
            <li
              key={d.id}
              className="rounded-lg border border-slate-800 bg-slate-900/60 p-2.5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-slate-100" title={d.filename}>
                    {d.filename}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {d.pages} pages · {formatWhen(d.created_at)}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={deletingId === d.id}
                  onClick={() => void onDelete(d.id)}
                  className="shrink-0 rounded border border-slate-700 px-2 py-1 text-xs text-slate-400 hover:border-red-900/80 hover:bg-red-950/30 hover:text-red-300 disabled:opacity-50"
                >
                  {deletingId === d.id ? '…' : 'Delete'}
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
