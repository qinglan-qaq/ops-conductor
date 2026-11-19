<script setup lang="ts">
import { computed } from 'vue'
import type { Run, RunEventKind } from '@/api/types'

const props = defineProps<{
  run: Run
  visibleEventSeqs: Set<number>
  activeSeq: number | null
}>()

const emit = defineEmits<{ (event: 'seek-event', seq: number): void }>()

const tailKinds: RunEventKind[] = [
  'verification_passed',
  'compensation_triggered',
  'rpa_executed',
  'reconciliation_found',
  'report_generated',
]
const labels: Record<string, string> = {
  verification_passed: 'Verifier',
  compensation_triggered: '补偿',
  rpa_executed: 'RPA',
  reconciliation_found: '对账',
  report_generated: '报告',
}

const chips = computed(() =>
  tailKinds.flatMap((kind) => {
    const event = props.run.events.find((item) => item.kind === kind)
    return event ? [{ kind, event, label: labels[kind] ?? kind }] : []
  }),
)

function chipClass(seq: number): string {
  if (props.activeSeq === seq) return 'governance-chip--active'
  if (props.visibleEventSeqs.has(seq)) return 'governance-chip--done'
  return 'governance-chip--future'
}
</script>

<template>
  <section class="run-governance-strip" data-run-governance-strip aria-label="治理收尾">
    <p class="panel-kicker">Governance</p>
    <div class="governance-track">
      <button
        v-for="chip in chips"
        :key="chip.kind"
        class="governance-chip"
        :class="chipClass(chip.event.seq)"
        type="button"
        data-governance-chip
        :data-event-seq="chip.event.seq"
        @click="emit('seek-event', chip.event.seq)"
      >
        <span>{{ chip.label }}</span>
        <small class="mono">#{{ chip.event.seq }}</small>
      </button>
    </div>
  </section>
</template>
