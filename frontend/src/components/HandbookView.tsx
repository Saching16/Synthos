import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  fetchDocuments,
  handbookDownloadUrl,
  openHandbookSse,
  type Document,
} from '../api'

type Props = {
  topic: string
  onTopicChange: (value: string) => void
}

const mdComponents = {
  p: ({ children }: { children?: ReactNode }) => (
    <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>
  ),
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="my-1 list-disc space-y-0.5 pl-4">{children}</ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="my-1 list-decimal space-y-0.5 pl-4">{children}</ol>
  ),
  li: ({ children }: { children?: ReactNode }) => (
    <li className="leading-relaxed">{children}</li>
  ),
  h1: ({ children }: { children?: ReactNode }) => (
    <h1 className="mt-4 mb-2 text-xl font-semibold text-slate-50 first:mt-0">{children}</h1>
  ),
  h2: ({ children }: { children?: ReactNode }) => (
    <h2 className="mt-3 mb-1.5 text-lg font-semibold text-slate-100">{children}</h2>
  ),
  h3: ({ children }: { children?: ReactNode }) => (
    <h3 className="mt-2 mb-1 text-base font-semibold text-slate-200">{children}</h3>
  ),
  strong: ({ children }: { children?: ReactNode }) => (
    <strong className="font-semibold text-slate-100">{children}</strong>
  ),
  hr: () => <hr className="my-4 border-slate-700" />,
  code: ({ className, children }: { className?: string; children?: ReactNode }) => {
    const inline = !className
    return inline ? (
      <code className="rounded bg-slate-800 px-1 py-0.5 font-mono text-xs text-sky-200">
        {children}
      </code>
    ) : (
      <code className={className}>{children}</code>
    )
  },
  pre: ({ children }: { children?: ReactNode }) => (
    <pre className="my-2 overflow-x-auto rounded-lg bg-slate-900 p-2 text-xs">{children}</pre>
  ),
}

/** Sections at least this long are collapsed until “Read more” is used. */
const SECTION_COLLAPSE_MIN_CHARS = 360

function HandbookPreviewSection({
  markdown,
  sectionIndex,
  expanded,
  onToggle,
}: {
  markdown: string
  sectionIndex: number
  expanded: boolean
  onToggle: (sectionIndex: number) => void
}) {
  const needsToggle = markdown.length >= SECTION_COLLAPSE_MIN_CHARS
  return (
    <article className="border-b border-slate-800/70 py-3 first:pt-0 last:border-b-0 last:pb-0">
      <div
        className={
          needsToggle && !expanded
            ? 'max-h-56 overflow-hidden [mask-image:linear-gradient(to_bottom,black_72%,transparent)]'
            : ''
        }
      >
        <div className="[&_a]:text-sky-400 [&_a]:underline">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {markdown}
          </ReactMarkdown>
        </div>
      </div>
      {needsToggle ? (
        <button
          type="button"
          onClick={() => onToggle(sectionIndex)}
          className="mt-2 text-xs font-medium text-sky-400 hover:text-sky-300"
        >
          {expanded ? 'Show less' : 'Read more'}
        </button>
      ) : null}
    </article>
  )
}

export function HandbookView({ topic, onTopicChange }: Props) {
  const [docs, setDocs] = useState<Document[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [planTotal, setPlanTotal] = useState(0)
  const [maxIdx, setMaxIdx] = useState(0)
  const [runningWords, setRunningWords] = useState(0)
  const [expandingNote, setExpandingNote] = useState<string | null>(null)
  const [bodies, setBodies] = useState<(string | undefined)[]>([])
  const [doneId, setDoneId] = useState<string | null>(null)
  const [doneWords, setDoneWords] = useState(0)
  const [expandedSections, setExpandedSections] = useState<Set<number>>(
    () => new Set(),
  )
  const previewRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const runLockRef = useRef(false)

  useEffect(() => {
    void fetchDocuments().then(setDocs).catch(() => setDocs([]))
  }, [])

  useEffect(() => {
    const el = previewRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [bodies, expandingNote])

  const toggleDoc = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const cancelRun = () => {
    abortRef.current?.abort()
  }

  const run = useCallback(async () => {
    const t = topic.trim()
    if (!t || runLockRef.current) return
    runLockRef.current = true
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    const signal = abortRef.current.signal

    setStreaming(true)
    setError(null)
    setPlanTotal(0)
    setMaxIdx(0)
    setRunningWords(0)
    setExpandingNote(null)
    setBodies([])
    setDoneId(null)
    setDoneWords(0)
    setExpandedSections(new Set())

    const payload: { topic: string; document_ids?: string[] } = { topic: t }
    if (selectedIds.size > 0) {
      payload.document_ids = Array.from(selectedIds)
    }

    try {
      await openHandbookSse(
        payload,
        {
          onPlanReady: ({ total_steps }) => {
            setPlanTotal(total_steps)
            setBodies(Array.from({ length: Math.max(total_steps, 0) }, () => undefined))
          },
          onParagraph: ({ index, total, text, running_total }) => {
            setPlanTotal((prev) => (total > prev ? total : prev))
            setMaxIdx((m) => Math.max(m, index))
            setRunningWords(running_total)
            setBodies((prev) => {
              const next = [...prev]
              const i = index - 1
              if (i >= 0) {
                while (next.length <= i) next.push(undefined)
                next[i] = text
              }
              return next
            })
          },
          onExpanding: ({ current_words, target_floor, target_cap }) => {
            setExpandingNote(
              `Expanding: ${current_words.toLocaleString()} words (target ${target_floor.toLocaleString()}–${target_cap.toLocaleString()})`,
            )
          },
          onDone: ({ id, words }) => {
            setDoneId(id)
            setDoneWords(words)
            setExpandingNote(null)
          },
          onError: (msg) => setError(msg),
        },
        signal,
      )
    } catch (e) {
      if (signal.aborted) {
        setError('Cancelled.')
      } else {
        setError(e instanceof Error ? e.message : 'Handbook request failed')
      }
    } finally {
      runLockRef.current = false
      setStreaming(false)
    }
  }, [topic, selectedIds])

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    void run()
  }

  const pct =
    planTotal > 0 ? Math.min(100, Math.round((100 * maxIdx) / planTotal)) : 0

  const title = topic.trim() || 'Handbook'
  const sectionEntries = bodies
    .map((body, index) =>
      typeof body === 'string' && body.trim().length > 0
        ? { index, text: body.trim() }
        : null,
    )
    .filter((x): x is { index: number; text: string } => x !== null)

  const toggleSectionExpanded = (sectionIndex: number) => {
    setExpandedSections((prev) => {
      const next = new Set(prev)
      if (next.has(sectionIndex)) next.delete(sectionIndex)
      else next.add(sectionIndex)
      return next
    })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <form onSubmit={onSubmit} className="flex shrink-0 flex-col gap-2">
        <label className="text-xs font-medium text-slate-400" htmlFor="hb-topic-field">
          Topic
        </label>
        <input
          id="hb-topic-field"
          type="text"
          value={topic}
          onChange={(e) => onTopicChange(e.target.value)}
          disabled={streaming}
          placeholder="e.g. Handbook on Retrieval-Augmented Generation"
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-600 focus:outline-none disabled:opacity-50"
        />
        {docs.length > 0 ? (
          <fieldset className="rounded-lg border border-slate-800 p-2">
            <legend className="px-1 text-xs text-slate-500">
              Optional: limit retrieval to selected PDFs (empty = all ingested)
            </legend>
            <ul className="scroll-pane max-h-40 space-y-1 text-xs">
              {docs.map((d) => (
                <li key={d.id} className="flex items-center gap-2">
                  <input
                    id={`doc-${d.id}`}
                    type="checkbox"
                    checked={selectedIds.has(d.id)}
                    onChange={() => toggleDoc(d.id)}
                    disabled={streaming}
                    className="rounded border-slate-600"
                  />
                  <label htmlFor={`doc-${d.id}`} className="truncate text-slate-300">
                    {d.filename}
                  </label>
                </li>
              ))}
            </ul>
          </fieldset>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={streaming || !topic.trim()}
            className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-40"
          >
            {streaming ? 'Generating…' : 'Generate'}
          </button>
          <button
            type="button"
            disabled={!streaming}
            onClick={cancelRun}
            className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-40"
          >
            Cancel
          </button>
        </div>
      </form>

      {error ? (
        <p className="rounded border border-red-900/60 bg-red-950/30 px-2 py-1.5 text-xs text-red-200">
          {error}
        </p>
      ) : null}

      {streaming || planTotal > 0 ? (
        <div className="shrink-0 space-y-1 rounded-lg border border-slate-800 bg-slate-900/40 p-2 text-xs text-slate-400">
          <div className="flex justify-between gap-2">
            <span>
              Paragraphs: {planTotal ? `${maxIdx} / ${planTotal}` : '…'}
            </span>
            <span>Words: {runningWords.toLocaleString()}</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full bg-emerald-600 transition-[width] duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
          {expandingNote ? <p className="text-amber-200/90">{expandingNote}</p> : null}
        </div>
      ) : null}

      {doneId ? (
        <div className="flex flex-wrap gap-2 text-sm">
          <span className="text-slate-400">
            Done ({doneWords.toLocaleString()} words).
          </span>
          <a
            href={handbookDownloadUrl(doneId, 'md')}
            download
            className="text-sky-400 underline hover:text-sky-300"
          >
            Download .md
          </a>
          <a
            href={handbookDownloadUrl(doneId, 'pdf')}
            download
            className="text-sky-400 underline hover:text-sky-300"
          >
            Download .pdf
          </a>
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col">
        <h3 className="mb-1 shrink-0 text-xs font-medium uppercase tracking-wide text-slate-500">
          Live preview
        </h3>
        <div
          ref={previewRef}
          className="scroll-pane min-h-0 flex-1 rounded-lg border border-slate-800 bg-slate-900/50 p-3 text-sm text-slate-200"
        >
          <div className="[&_a]:text-sky-400 [&_a]:underline">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
              {`# ${title}`}
            </ReactMarkdown>
          </div>
          {sectionEntries.length === 0 ? (
            <p className="mt-2 text-sm italic text-slate-500">Generating…</p>
          ) : (
            sectionEntries.map(({ index, text }) => (
              <HandbookPreviewSection
                key={index}
                sectionIndex={index}
                markdown={`## Section ${index + 1}\n\n${text}`}
                expanded={expandedSections.has(index)}
                onToggle={toggleSectionExpanded}
              />
            ))
          )}
        </div>
      </div>
    </div>
  )
}
