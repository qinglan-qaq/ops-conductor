<script setup lang="ts">
import { computed } from 'vue'
import type { IntegrationPlatform } from '@/api/types'
import CapabilityBadge from './CapabilityBadge.vue'
import FreshnessBadge from './FreshnessBadge.vue'

const props = defineProps<{ platform: IntegrationPlatform }>()

const dataCapabilities = computed(() =>
  props.platform.capabilities.filter((item) => item.startsWith('data.')),
)
const controlCapabilities = computed(() =>
  props.platform.capabilities.filter((item) => item.startsWith('control.')),
)
</script>

<template>
  <article class="integration-card" :data-integration-platform="platform.platform">
    <header class="integration-card-head">
      <div>
        <p class="panel-kicker">{{ platform.platform }} · {{ platform.shop_id }}</p>
        <h2>{{ platform.name }}</h2>
      </div>
      <div class="integration-status-badges">
        <span class="mock-pill">{{ platform.status }}</span>
        <span class="mode-pill">{{ platform.mode }}</span>
        <FreshnessBadge :freshness="platform.freshness" />
      </div>
    </header>

    <dl class="integration-facts">
      <div>
        <dt>最近同步</dt>
        <dd class="mono">{{ platform.last_sync_at ?? '—' }}</dd>
      </div>
      <div>
        <dt>数据能力</dt>
        <dd class="mono">{{ dataCapabilities.length }}</dd>
      </div>
      <div>
        <dt>控制能力</dt>
        <dd class="mono">{{ controlCapabilities.length }}</dd>
      </div>
    </dl>

    <section class="capability-section">
      <h3>数据获取</h3>
      <div class="capability-list">
        <CapabilityBadge
          v-for="capability in dataCapabilities"
          :key="capability"
          :capability="capability"
        />
      </div>
    </section>

    <section class="capability-section">
      <h3>控制写入</h3>
      <div class="capability-list">
        <CapabilityBadge
          v-for="capability in controlCapabilities"
          :key="capability"
          :capability="capability"
        />
      </div>
      <p class="capability-note">
        控制动作必须经 ControlService：审批 → 幂等 → dry-run → 执行 → 补偿。
        页面仅按 capability 显示动作。
      </p>
    </section>

    <p v-if="platform.warnings.length" class="integration-warning">
      {{ platform.warnings.join('；') }}
    </p>
    <p v-else class="integration-ok">
      Mock Adapter 健康；本期未接真实凭据、OAuth 或生产平台 API。
    </p>
  </article>
</template>
