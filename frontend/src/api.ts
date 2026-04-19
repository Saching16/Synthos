/**
 * API base URL (no trailing slash). Set in `.env` as `VITE_API_BASE`.
 */
export function apiUrl(path: string): string {
  const base = import.meta.env.VITE_API_BASE?.replace(/\/$/, '') ?? ''
  const p = path.startsWith('/') ? path : `/${path}`
  return `${base}${p}`
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
