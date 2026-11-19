/** 后端返回的可归因 HTTP 错误；视图层可只依赖本文件判断错误类型。 */
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
