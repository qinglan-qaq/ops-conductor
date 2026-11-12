import { readonly, ref } from 'vue'

export type ToastKind = 'ink' | 'red' | 'gold'

const message = ref('')
const kind = ref<ToastKind>('ink')
const visible = ref(false)
let timer: number | undefined

/** 全局轻提示；同一时刻只显示一条，避免多操作堆叠。 */
export function useToast() {
  function show(text: string, tone: ToastKind = 'ink'): void {
    message.value = text
    kind.value = tone
    visible.value = true
    if (timer !== undefined) {
      window.clearTimeout(timer)
    }
    timer = window.setTimeout(() => {
      visible.value = false
    }, 4_200)
  }

  return {
    message: readonly(message),
    kind: readonly(kind),
    visible: readonly(visible),
    show,
  }
}
