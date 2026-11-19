<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { RunAgent, RunArtifact, RunGate, RunStep } from '@/api/types'
import RunGateCard from './RunGateCard.vue'

defineProps<{
  step: RunStep
  agent: RunAgent
  artifact: RunArtifact | null
  gate: RunGate | null
  gateStatus: RunGate['status'] | null
  previous: RunStep | null
  next: RunStep | null
}>()

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'seek-step', stepId: string): void
}>()

const closeButton = ref<HTMLButtonElement | null>(null)

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => {
  document.body.classList.add('drawer-locked')
  closeButton.value?.focus()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.body.classList.remove('drawer-locked')
  window.removeEventListener('keydown', onKeydown)
})

function isRedacted(value: unknown): boolean {
  return JSON.stringify(value).includes('***')
}
</script>

<template>
  <Teleport to="body">
    <div class="drawer-backdrop" @click.self="emit('close')">
      <aside
        class="run-step-drawer"
        role="dialog"
        aria-modal="true"
        :aria-label="`${step.name} 运行详情`"
        data-step-drawer
      >
        <header class="drawer-head">
          <div>
            <p class="panel-kicker">Step {{ step.index }} · {{ step.stage }}</p>
            <h2>{{ step.name }}</h2>
            <p class="run-drawer-sub">
              {{ agent.name }} · {{ agent.role }} · {{ step.risk }} · {{ step.duration_ms }}ms
            </p>
          </div>
          <button
            ref="closeButton"
            class="drawer-close"
            type="button"
            aria-label="关闭步骤详情"
            @click="emit('close')"
          >
            关闭
          </button>
        </header>

        <section class="drawer-section">
          <h3>能力匹配</h3>
          <p>
            <code>{{ step.capability }}</code> 由 {{ agent.name }} 提供；可选能力：
            {{ agent.capabilities.join(' / ') }}
          </p>
          <p>{{ step.summary }}</p>
        </section>

        <section class="drawer-section">
          <h3>工具调用</h3>
          <div v-for="call in step.tool_calls" :key="`${call.tool}-${call.duration_ms}`" data-tool-call>
            <p><strong>{{ call.tool }}</strong> · {{ call.duration_ms }}ms · {{ call.status }}</p>
            <p class="run-drawer-label">
              参数
              <span v-if="isRedacted(call.params)">已脱敏</span>
            </p>
            <pre>{{ JSON.stringify(call.params, null, 2) }}</pre>
            <p class="run-drawer-label">返回</p>
            <pre>{{ JSON.stringify(call.result, null, 2) }}</pre>
          </div>
        </section>

        <section class="drawer-section">
          <h3>产物</h3>
          <p v-if="artifact">
            <span class="mono">{{ artifact.name }}</span> · {{ artifact.kind }} ·
            <span class="mono">{{ artifact.uri }}</span>
          </p>
          <p v-else>本步骤没有产物。</p>
        </section>

        <section v-if="gate" class="drawer-section">
          <h3>审批门禁</h3>
          <RunGateCard :gate="gate" :status="gateStatus ?? 'pending'" />
        </section>

        <section class="drawer-section">
          <h3>上下游</h3>
          <div class="run-drawer-links">
            <button
              v-if="previous"
              class="button button-quiet"
              type="button"
              data-upstream
              @click="emit('seek-step', previous.id)"
            >
              ← {{ previous.name }}
            </button>
            <span v-else class="section-note">起点</span>
            <button
              v-if="next"
              class="button button-quiet"
              type="button"
              data-downstream
              @click="emit('seek-step', next.id)"
            >
              {{ next.name }} →
            </button>
            <span v-else class="section-note">终点</span>
          </div>
        </section>
      </aside>
    </div>
  </Teleport>
</template>
