<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { Snapshot } from '@/api/types'
import StatusDot from '@/components/ui/StatusDot.vue'

defineProps<{ chain: Snapshot['chain'] }>()
</script>

<template>
  <section class="board-card" data-chain-matrix>
    <header class="board-card-head">
      <div>
        <p class="board-kicker">十段链路</p>
        <h2>链路状态矩阵</h2>
      </div>
      <span class="board-note">点格进入阶段工作台</span>
    </header>

    <div class="chain-matrix">
      <RouterLink
        v-for="stage in chain"
        :key="stage.id"
        class="chain-cell"
        :class="`chain-cell--${stage.status}`"
        :to="{ name: 'stage', params: { stageId: stage.id } }"
        :data-chain-stage="stage.id"
      >
        <StatusDot :status="stage.status" />
        <strong>{{ stage.name }}</strong>
        <span>{{ stage.meta }}</span>
      </RouterLink>
    </div>
  </section>
</template>
