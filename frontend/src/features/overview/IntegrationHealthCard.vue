<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { IntegrationsResponse } from '@/api/types'

const props = defineProps<{ integrations: IntegrationsResponse }>()

const platform = computed(() => props.integrations.platforms[0] ?? null)
</script>

<template>
  <section class="board-card" data-integration-health>
    <header class="board-card-head">
      <div>
        <p class="board-kicker">平台集成</p>
        <h2>{{ platform?.name ?? '未配置平台' }}</h2>
      </div>
      <RouterLink class="text-link" to="/dispatch/integrations">集成 →</RouterLink>
    </header>

    <template v-if="platform">
      <div class="integration-line">
        <span class="mock-pill">{{ platform.status }} · {{ platform.mode }}</span>
        <span class="freshness" :class="`freshness--${platform.freshness}`">
          {{ platform.freshness }}
        </span>
      </div>
      <dl class="integration-facts">
        <div>
          <dt>店铺</dt>
          <dd>{{ platform.shop_id }}</dd>
        </div>
        <div>
          <dt>最近同步</dt>
          <dd>{{ platform.last_sync_at ?? '—' }}</dd>
        </div>
        <div>
          <dt>能力</dt>
          <dd>{{ platform.capabilities.length }} 项</dd>
        </div>
      </dl>
      <p v-if="platform.warnings.length" class="integration-warning">
        {{ platform.warnings.join('；') }}
      </p>
      <p v-else class="integration-ok">Mock Adapter 在线 · 未接真实平台凭据</p>
    </template>
    <p v-else class="integration-warning">尚未注册 Adapter，控制写不可用。</p>
  </section>
</template>
