<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    status: string
    label?: string
    showLabel?: boolean
  }>(),
  { label: '', showLabel: false },
)

const labels: Record<string, string> = {
  done: '完成',
  running: '进行中',
  alert: '异常',
  waiting: '待办',
  idle: '空闲',
  error: '失败',
}

const text = computed(() => props.label || labels[props.status] || props.status)
const tone = computed(() => {
  if (props.status === 'alert' || props.status === 'error') return 'alert'
  if (props.status === 'running') return 'running'
  if (props.status === 'done') return 'done'
  if (props.status === 'waiting') return 'waiting'
  return 'idle'
})
</script>

<template>
  <span
    class="status-dot"
    :class="`status-dot--${tone}`"
    :title="text"
    role="img"
    :aria-label="text"
  >
    <span class="status-dot-mark" aria-hidden="true" />
    <span v-if="showLabel" class="status-dot-text">{{ text }}</span>
  </span>
</template>
