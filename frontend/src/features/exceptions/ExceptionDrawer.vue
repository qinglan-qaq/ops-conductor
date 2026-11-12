<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { ExceptionCase } from '@/api/types'

defineProps<{ exception: ExceptionCase }>()
const emit = defineEmits<{ close: [] }>()

const closeButton = ref<HTMLButtonElement | null>(null)

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    emit('close')
  }
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
</script>

<template>
  <Teleport to="body">
    <div class="drawer-backdrop" @click.self="emit('close')">
      <aside
        class="exception-drawer"
        role="dialog"
        aria-modal="true"
        :aria-label="`${exception.id} ${exception.title} 处置手册`"
      >
        <header class="drawer-head">
          <div>
            <p class="panel-kicker">{{ exception.id }} · {{ exception.li }}</p>
            <h2>{{ exception.title }}</h2>
          </div>
          <button
            ref="closeButton"
            class="drawer-close"
            type="button"
            aria-label="关闭异常手册"
            @click="emit('close')"
          >
            关闭
          </button>
        </header>

        <div class="drawer-meta">
          <span :class="`priority-code priority-code--${exception.priority.toLowerCase()}`">
            {{ exception.priority }}
          </span>
          <span>{{ exception.sla }}</span>
          <span>{{ exception.owner }}</span>
          <span>{{ exception.count }}</span>
        </div>

        <section class="drawer-section">
          <h3>触发条件</h3>
          <p>{{ exception.playbook.trigger }}</p>
        </section>

        <section class="drawer-section">
          <h3>分阶段处置</h3>
          <ol class="playbook-phases">
            <li v-for="phase in exception.playbook.phases" :key="phase.label">
              <h4>{{ phase.label }}</h4>
              <ul>
                <li v-for="step in phase.steps" :key="step">{{ step }}</li>
              </ul>
            </li>
          </ol>
        </section>

        <section class="drawer-section">
          <h3>Agent 自动化</h3>
          <p>{{ exception.playbook.automation }}</p>
        </section>

        <footer class="drawer-foot">
          <span class="mono">阶段 {{ exception.stage_id || '全局' }}</span>
          <span>只读 Playbook · 执行需审批</span>
        </footer>
      </aside>
    </div>
  </Teleport>
</template>
