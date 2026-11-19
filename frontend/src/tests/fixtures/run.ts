import raw from './run.json'
import { RunSchema } from '@/api/schemas'

/** 测试专用 Run fixture；由后端真实序列化结果生成，不做生产离线 fallback。 */
export const runFixture = RunSchema.parse(raw)
