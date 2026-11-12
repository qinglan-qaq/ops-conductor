<script setup lang="ts">
import { computed } from 'vue'
import { fallbackIntegrations } from '@/api/fixtures'
import { useIntegrationsQuery } from '@/queries/useIntegrationsQuery'
import IntegrationStatus from './IntegrationStatus.vue'

const integrationsQuery = useIntegrationsQuery()

const integrations = computed(
  () => integrationsQuery.data.value ?? fallbackIntegrations,
)
</script>

<template>
  <div class="page" data-integrations-view>
    <header class="page-head">
      <div>
        <p class="page-kicker">Integrations · 平台边界</p>
        <h1>平台集成健康</h1>
        <p class="page-lede">
          平台差异被限制在 Adapter、canonical 映射与 manifest；页面只读
          capability，不按平台名写分支。
        </p>
      </div>
      <span class="page-count mono">{{ integrations.platforms.length }} 平台/店铺</span>
    </header>

    <div class="readonly-banner" role="status">
      <strong>本期只读</strong>
      <span>
        已实现 MockPlatformAdapter 与集成健康视图；真实同步
        <code>POST /sync-runs</code> 与控制写 <code>POST /control/commands</code>
        尚未启用。
      </span>
    </div>

    <div class="integration-grid">
      <IntegrationStatus
        v-for="platform in integrations.platforms"
        :key="`${platform.platform}-${platform.shop_id}`"
        :platform="platform"
      />
    </div>
    <p v-if="integrations.platforms.length === 0" class="empty-state">
      尚未注册 Adapter。
    </p>
  </div>
</template>
