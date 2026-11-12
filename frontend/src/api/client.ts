import type { z } from 'zod'

/** API 基址；生产由 FastAPI 同源托管，开发由 Vite 代理到 8010。 */
export const API_BASE = (
  import.meta.env.VITE_API_BASE ?? '/api/v1/dispatch'
).replace(/\/$/, '')

const REQUEST_TIMEOUT_MS = 15_000

/** 后端返回的可归因 HTTP 错误。 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly retryable: boolean

  constructor(status: number, code: string, detail: string, retryable: boolean) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.retryable = retryable
  }
}

/** 响应未通过 Zod 契约校验；不得让缺字段进入组件。 */
export class ApiContractError extends Error {
  readonly issues: string[]

  constructor(message: string, issues: string[] = []) {
    super(message)
    this.name = 'ApiContractError'
    this.issues = issues
  }
}

function detailOf(payload: unknown): string | null {
  if (
    payload !== null &&
    typeof payload === 'object' &&
    'detail' in payload &&
    typeof payload.detail === 'string'
  ) {
    return payload.detail
  }
  return null
}

function codeOf(payload: unknown): string | null {
  if (
    payload !== null &&
    typeof payload === 'object' &&
    'code' in payload &&
    typeof payload.code === 'string'
  ) {
    return payload.code
  }
  return null
}

function isRetryable(status: number): boolean {
  return status === 408 || status === 429 || status >= 500
}

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init: RequestInit = {},
): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  const sourceSignal = init.signal
  const abortFromSource = () => controller.abort()
  if (sourceSignal) {
    if (sourceSignal.aborted) {
      controller.abort()
    } else {
      sourceSignal.addEventListener('abort', abortFromSource, { once: true })
    }
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(0, 'aborted', '请求已取消或超时', true)
    }
    throw new ApiError(0, 'network_error', '无法连接后端', true)
  } finally {
    window.clearTimeout(timer)
    sourceSignal?.removeEventListener('abort', abortFromSource)
  }

  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      codeOf(payload) ?? `http_${response.status}`,
      detailOf(payload) ?? response.statusText,
      isRetryable(response.status),
    )
  }

  if (payload === null) {
    throw new ApiContractError('后端返回空响应，无法校验契约')
  }

  const parsed = schema.safeParse(payload)
  if (!parsed.success) {
    throw new ApiContractError(
      '后端响应不符合前端契约',
      parsed.error.issues.map(
        (issue) => `${issue.path.join('.') || '(root)'}: ${issue.message}`,
      ),
    )
  }
  return parsed.data
}

export { request }
