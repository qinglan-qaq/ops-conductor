<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { ResultDelivery } from '@/api/types'

const props = defineProps<{ results: ResultDelivery }>()

const maxArtifacts = computed(() =>
  Math.max(...props.results.stages.map((stage) => stage.artifact_count), 1),
)
</script>

<template>
  <section class="panel chart-panel" data-result-delivery-chart>
    <header class="chart-head">
      <div>
        <p class="panel-kicker">返回结果</p>
        <h2>阶段结果交付</h2>
      </div>
      <div class="chart-summary">
        <strong class="mono">{{ results.total_results }}/10</strong>
        <span class="mono">{{ results.artifact_count }} 产物</span>
        <em>{{ results.evidence_count }} 证据</em>
      </div>
    </header>

    <div class="result-grid">
      <RouterLink
        v-for="stage in results.stages"
        :key="stage.stage_id"
        class="result-tile"
        :class="`result-tile--${stage.status}`"
        :to="{ name: 'stage', params: { stageId: stage.stage_id } }"
        :data-result-stage="stage.stage_id"
      >
        <span class="result-name">{{ stage.name }}</span>
        <span class="result-track" aria-hidden="true">
          <span
            class="result-fill"
            :style="{ width: `${(stage.artifact_count / maxArtifacts) * 100}%` }"
          />
        </span>
        <span class="result-meta">
          <strong class="mono">{{ stage.artifact_count }}</strong> 产物 ·
          {{ stage.evidence_count }} 证据
        </span>
      </RouterLink>
    </div>
  </section>
</template>
