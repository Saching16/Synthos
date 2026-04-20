/**
 * API base URL (no trailing slash). Set in `.env` as `VITE_API_BASE`.
 */
export function apiUrl(path: string): string {
  const base = import.meta.env.VITE_API_BASE?.replace(/\/$/, '') ?? ''
  const p = path.startsWith('/') ? path : `/${path}`
  return `${base}${p}`
}

export type UploadResult = {
  id: string
  filename: string
  pages: number
  char_count: number
  status: 'ingested' | 'duplicate'
}

export type Document = {
  id: string
  filename: string
  sha256: string
  pages: number
  char_count: number
  created_at: string
}

export async function fetchDocuments(): Promise<Document[]> {
  const res = await fetch(apiUrl('/documents'))
  if (!res.ok) {
    const t = await res.text().catch(() => '')
    throw new Error(`Documents failed: ${res.status} ${t}`)
  }
  return res.json() as Promise<Document[]>
}

export async function deleteDocument(id: string): Promise<void> {
  const res = await fetch(apiUrl(`/documents/${id}`), { method: 'DELETE' })
  if (res.status === 204) return
  if (res.status === 404) {
    throw new Error('Document not found')
  }
  const t = await res.text().catch(() => '')
  throw new Error(`Delete failed: ${res.status} ${t}`)
}

/**
 * Multipart POST to `/upload` with optional upload progress (single request, all files).
 */
export function uploadPdfs(
  files: File[],
  onProgress?: (loaded: number, total: number) => void,
): Promise<UploadResult[]> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const fd = new FormData()
    for (const f of files) {
      fd.append('files', f, f.name)
    }
    xhr.open('POST', apiUrl('/upload'))
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) {
        onProgress?.(ev.loaded, ev.total)
      }
    }
    xhr.onload = () => {
      if (xhr.status === 0) {
        reject(
          new Error(
            'Upload failed: no response (API unreachable, wrong URL, or browser blocked the request). ' +
              'For `npm run dev`, leave `VITE_API_BASE` unset so `/upload` is proxied to port 8000, ' +
              'or set `VITE_API_BASE` to your API origin (e.g. http://127.0.0.1:8000).',
          ),
        )
        return
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        let data: UploadResult[]
        try {
          data = JSON.parse(xhr.responseText || 'null') as UploadResult[]
          if (!Array.isArray(data)) {
            throw new Error('not an array')
          }
        } catch {
          reject(
            new Error(
              `Upload failed: bad JSON (${xhr.status}): ${(xhr.responseText || '').slice(0, 240)}`,
            ),
          )
          return
        }
        resolve(data)
        return
      }
      let msg = xhr.responseText || xhr.statusText
      try {
        const j = JSON.parse(xhr.responseText) as { detail?: unknown }
        if (j.detail != null) {
          msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
        }
      } catch {
        /* keep body or statusText */
      }
      reject(new Error(`Upload failed: ${xhr.status} ${msg}`))
    }
    xhr.onerror = () =>
      reject(
        new Error(
          'Upload failed: network error (browser could not complete the request). ' +
            'Start the API on port 8000, or set `VITE_DEV_PROXY_TARGET` in the env used by Vite if the API uses another host/port.',
        ),
      )
    xhr.send(fd)
  })
}

export type ChatHistoryItem = { role: string; content: string }

export type ChatSseCallbacks = {
  onToken?: (text: string) => void
  onDone?: () => void
  onRedirect?: (payload: { path: string; topic: string; message?: string }) => void
  onError?: (message: string) => void
}

/**
 * POST `/chat` (SSE): `token` deltas, `done`, optional `redirect`, `error`.
 */
export async function openChatSse(
  body: { message: string; history: ChatHistoryItem[] },
  callbacks: ChatSseCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  return openSse(
    '/chat',
    body,
    {
      onEvent: (eventType, data) => {
        try {
          if (eventType === 'token') {
            const j = JSON.parse(data) as { text?: string }
            if (j.text) callbacks.onToken?.(j.text)
            return
          }
          if (eventType === 'done') {
            callbacks.onDone?.()
            return
          }
          if (eventType === 'redirect') {
            const j = JSON.parse(data) as {
              path: string
              topic: string
              message?: string
            }
            callbacks.onRedirect?.(j)
            return
          }
          if (eventType === 'error') {
            const j = JSON.parse(data) as { message?: string }
            callbacks.onError?.(j.message ?? 'Chat request failed')
          }
        } catch {
          callbacks.onError?.('Malformed server event')
        }
      },
    },
    signal,
  )
}

export type HandbookSseCallbacks = {
  /** Fired before the planner LLM runs; no paragraphs are written until after ``plan_ready``. */
  onPlanning?: () => void
  onPlanReady?: (p: {
    total_steps: number
    target_words_sum: number
    /** Full outline (``Paragraph N - Main Point: …`` lines) shown before drafting. */
    plan_text?: string
  }) => void
  onParagraph?: (p: {
    index: number
    total: number
    text: string
    words: number
    running_total: number
    phase?: string
  }) => void
  onExpanding?: (p: {
    current_words: number
    target_floor: number
    target_cap: number
  }) => void
  onDone?: (p: { id: string; words: number; topic: string }) => void
  onError?: (message: string) => void
}

/**
 * POST `/handbook` (SSE): `planning`, `plan_ready`, `paragraph`, `expanding`, `done`, `error`.
 */
export async function openHandbookSse(
  body: { topic: string; document_ids?: string[] },
  callbacks: HandbookSseCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  return openSse('/handbook', body, {
    onEvent: (eventType, data) => {
      try {
        const j = JSON.parse(data) as Record<string, unknown>
        if (eventType === 'planning') {
          callbacks.onPlanning?.()
          return
        }
        if (eventType === 'plan_ready') {
          callbacks.onPlanReady?.({
            total_steps: Number(j.total_steps ?? 0),
            target_words_sum: Number(j.target_words_sum ?? 0),
            plan_text:
              typeof j.plan_text === 'string' && j.plan_text.trim()
                ? j.plan_text
                : undefined,
          })
          return
        }
        if (eventType === 'paragraph') {
          callbacks.onParagraph?.({
            index: Number(j.index ?? 0),
            total: Number(j.total ?? 0),
            text: String(j.text ?? ''),
            words: Number(j.words ?? 0),
            running_total: Number(j.running_total ?? 0),
            phase: typeof j.phase === 'string' ? j.phase : undefined,
          })
          return
        }
        if (eventType === 'expanding') {
          callbacks.onExpanding?.({
            current_words: Number(j.current_words ?? 0),
            target_floor: Number(j.target_floor ?? 0),
            target_cap: Number(j.target_cap ?? 0),
          })
          return
        }
        if (eventType === 'done') {
          callbacks.onDone?.({
            id: String(j.id ?? ''),
            words: Number(j.words ?? 0),
            topic: String(j.topic ?? ''),
          })
          return
        }
        if (eventType === 'error') {
          const msg =
            typeof j.message === 'string' ? j.message : 'Handbook generation failed'
          callbacks.onError?.(msg)
        }
      } catch {
        callbacks.onError?.('Malformed server event')
      }
    },
  }, signal)
}

export function handbookDownloadUrl(id: string, format: 'md' | 'pdf'): string {
  return apiUrl(
    `/handbook/${encodeURIComponent(id)}/download?format=${format}`,
  )
}

export type SseHandlers = {
  onOpen?: () => void
  onEvent?: (eventType: string, data: string) => void
  onError?: (err: Error) => void
}

/**
 * POST JSON and consume `text/event-stream` (SSE) with named events.
 * Parses blocks of `event:` + `data:` lines (data may be JSON).
 */
export async function openSse(
  path: string,
  body: unknown,
  handlers: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(apiUrl(path), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`SSE request failed: ${res.status} ${text}`)
  }
  if (!res.body) {
    throw new Error('No response body')
  }
  handlers.onOpen?.()

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventType = 'message'

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          const data = line.slice(5).trimStart()
          handlers.onEvent?.(eventType, data)
          eventType = 'message'
        }
      }
    }
  } catch (e) {
    const err = e instanceof Error ? e : new Error(String(e))
    handlers.onError?.(err)
    throw err
  }
}

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch(apiUrl('/health'))
  if (!res.ok) {
    throw new Error(`Health check failed: ${res.status}`)
  }
  return res.json() as Promise<{ status: string }>
}
