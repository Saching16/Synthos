import { useCallback, useId, useState } from 'react'
import { uploadPdfs, type UploadResult } from '../api'

type Row =
  | { kind: 'pending'; name: string }
  | {
      kind: 'done'
      name: string
      result: UploadResult
    }
  | { kind: 'error'; name: string; message: string }

type Props = {
  onUploaded?: () => void
}

function isPdf(file: File): boolean {
  const n = file.name.toLowerCase()
  return n.endsWith('.pdf') || file.type === 'application/pdf'
}

export function Uploader({ onUploaded }: Props) {
  const inputId = useId()
  const [dragOver, setDragOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [rows, setRows] = useState<Row[]>([])
  const [toast, setToast] = useState<string | null>(null)

  const runUpload = useCallback(
    async (files: File[]) => {
      const pdfs = files.filter(isPdf)
      if (!pdfs.length) {
        setToast('Only PDF files are accepted.')
        return
      }
      setBusy(true)
      setProgress(0)
      setRows(pdfs.map((f) => ({ kind: 'pending' as const, name: f.name })))
      setToast(null)
      try {
        const results = await uploadPdfs(pdfs, (loaded, total) => {
          setProgress(total ? Math.round((100 * loaded) / total) : 0)
        })
        setRows(
          results.map((r) => ({
            kind: 'done' as const,
            name: r.filename,
            result: r,
          })),
        )
        const dupes = results.filter((r) => r.status === 'duplicate').length
        if (dupes) {
          setToast(
            dupes === results.length
              ? 'All files were already ingested (duplicates).'
              : `${dupes} file(s) were duplicates; others ingested.`,
          )
        }
        onUploaded?.()
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Upload failed'
        setRows(
          pdfs.map((f) => ({
            kind: 'error' as const,
            name: f.name,
            message: msg,
          })),
        )
        setToast(msg)
      } finally {
        setBusy(false)
        setProgress(0)
      }
    },
    [onUploaded],
  )

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const list = e.target.files ? Array.from(e.target.files) : []
    e.target.value = ''
    if (list.length) void runUpload(list)
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const list = Array.from(e.dataTransfer.files)
    if (list.length) void runUpload(list)
  }

  return (
    <div className="space-y-3">
      {toast ? (
        <p
          className="rounded border border-amber-800/80 bg-amber-950/40 px-2 py-1.5 text-xs text-amber-200"
          role="status"
        >
          {toast}
        </p>
      ) : null}
      <label
        htmlFor={inputId}
        onDragEnter={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-3 py-6 text-center transition-colors ${
          dragOver
            ? 'border-sky-500 bg-sky-950/40'
            : 'border-slate-700 bg-slate-900/50 hover:border-slate-600'
        } ${busy ? 'pointer-events-none opacity-60' : ''}`}
      >
        <input
          id={inputId}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          className="sr-only"
          onChange={onInputChange}
        />
        <span className="text-sm text-slate-300">
          Drop PDFs here or{' '}
          <span className="text-sky-400 underline">choose files</span>
        </span>
        <span className="mt-1 text-xs text-slate-500">Multipart POST to /upload</span>
      </label>
      {busy ? (
        <div className="space-y-1">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full bg-sky-600 transition-[width] duration-150"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="text-xs text-slate-500">Uploading… {progress}%</p>
        </div>
      ) : null}
      {rows.length > 0 ? (
        <ul className="space-y-1.5 text-sm">
          {rows.map((row, i) => (
            <li
              key={`${row.name}-${i}`}
              className="flex items-center justify-between gap-2 rounded bg-slate-900/80 px-2 py-1.5"
            >
              <span className="truncate text-slate-200" title={row.name}>
                {row.name}
              </span>
              {row.kind === 'pending' ? (
                <span className="shrink-0 text-xs text-slate-500">…</span>
              ) : null}
              {row.kind === 'done' ? (
                <span
                  className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-medium ${
                    row.result.status === 'duplicate'
                      ? 'bg-amber-950 text-amber-300 ring-1 ring-amber-800'
                      : 'bg-emerald-950 text-emerald-300 ring-1 ring-emerald-800'
                  }`}
                >
                  {row.result.status === 'duplicate' ? 'Duplicate' : 'Ingested'}
                </span>
              ) : null}
              {row.kind === 'error' ? (
                <span className="shrink-0 text-xs text-red-400" title={row.message}>
                  Error
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
