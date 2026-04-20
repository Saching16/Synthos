import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { openChatSse, type ChatHistoryItem } from '../api'

export type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
}

type Props = {
  onHandbookRedirect: (topic: string) => void
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
  strong: ({ children }: { children?: ReactNode }) => (
    <strong className="font-semibold text-slate-100">{children}</strong>
  ),
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

function toHistoryPayload(msgs: ChatMessage[]): ChatHistoryItem[] {
  return msgs.map((m) => ({ role: m.role, content: m.content }))
}

export function Chat({ onHandbookRedirect }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, busy])

  const send = useCallback(async () => {
    const text = input.trim()
    if (!text || busy) return

    abortRef.current?.abort()
    abortRef.current = new AbortController()
    const signal = abortRef.current.signal

    const historyPayload = toHistoryPayload(messages)
    setInput('')
    setError(null)
    setBusy(true)
    setMessages((prev) => [...prev, { role: 'user', content: text }])

    let redirected = false

    try {
      await openChatSse(
        { message: text, history: historyPayload },
        {
          onToken: (delta) => {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last?.role === 'assistant') {
                return [
                  ...prev.slice(0, -1),
                  { role: 'assistant', content: last.content + delta },
                ]
              }
              return [...prev, { role: 'assistant', content: delta }]
            })
          },
          onRedirect: (payload) => {
            redirected = true
            setMessages((prev) => [
              ...prev,
              {
                role: 'assistant',
                content:
                  payload.message ??
                  'Opening the handbook workspace so you can generate a long-form guide.',
              },
            ])
            onHandbookRedirect(payload.topic)
          },
          onError: (msg) => {
            setError(msg)
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last?.role === 'assistant') {
                return [
                  ...prev.slice(0, -1),
                  {
                    role: 'assistant',
                    content: `${last.content}\n\n**Error:** ${msg}`,
                  },
                ]
              }
              return [...prev, { role: 'assistant', content: `**Error:** ${msg}` }]
            })
          },
          onDone: () => {},
        },
        signal,
      )
    } catch (e) {
      if (signal.aborted) return
      const msg = e instanceof Error ? e.message : 'Request failed'
      setError(msg)
      if (!redirected) {
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant' && last.content === '') {
            return [
              ...prev.slice(0, -1),
              {
                role: 'assistant',
                content: `Could not reach the server. Is the API running at the configured base URL? ${msg}`,
              },
            ]
          }
          if (last?.role === 'user') {
            return [
              ...prev,
              {
                role: 'assistant',
                content: `Could not reach the server. Is the API running? ${msg}`,
              },
            ]
          }
          return prev
        })
      }
    } finally {
      setBusy(false)
    }
  }, [busy, input, messages, onHandbookRedirect])

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {error ? (
        <p
          className="rounded border border-red-900/60 bg-red-950/30 px-2 py-1.5 text-xs text-red-200"
          role="alert"
        >
          {error}
        </p>
      ) : null}
      <div className="scroll-pane min-h-0 flex-1 space-y-3 pr-1">
        {messages.length === 0 ? (
          <p className="text-sm text-slate-500">
            Ask about your uploaded PDFs. For a long handbook, try: &quot;Create a
            handbook on RAG&quot;.
          </p>
        ) : null}
        {messages.map((m, i) => (
          <div
            key={`${i}-${m.role}`}
            className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[95%] rounded-2xl px-3 py-2 text-sm md:max-w-[90%] ${
                m.role === 'user'
                  ? 'bg-sky-900/50 text-slate-100'
                  : 'border border-slate-800 bg-slate-900/80 text-slate-200'
              }`}
            >
              {m.role === 'user' ? (
                <p className="whitespace-pre-wrap">{m.content}</p>
              ) : (
                <div className="[&_a]:text-sky-400 [&_a]:underline">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                    {m.content || (busy && i === messages.length - 1 ? '…' : '')}
                  </ReactMarkdown>
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <div className="flex shrink-0 flex-col gap-2 border-t border-slate-800 pt-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Message… (Enter to send, Shift+Enter for newline)"
          rows={2}
          disabled={busy}
          className="resize-none rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-600 focus:outline-none disabled:opacity-50"
        />
        <button
          type="button"
          disabled={busy || !input.trim()}
          onClick={() => void send()}
          className="self-end rounded-lg bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-600 disabled:opacity-40"
        >
          {busy ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  )
}
