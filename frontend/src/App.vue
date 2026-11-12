<script setup lang="ts">
import { computed } from 'vue'
import AppShell from '@/components/layout/AppShell.vue'
import { fallbackIntegrations, fallbackSnapshot } from '@/api/fixtures'
import { useSnapshotQuery } from '@/queries/useSnapshotQuery'
import { useIntegrationsQuery } from '@/queries/useIntegrationsQuery'

const snapshotQuery = useSnapshotQuery()
const integrationsQuery = useIntegrationsQuery()

const snapshot = computed(() => snapshotQuery.data.value ?? fallbackSnapshot)
const integrations = computed(
  () => integrationsQuery.data.value ?? fallbackIntegrations,
)
const offline = computed(
  () => snapshotQuery.isError.value || integrationsQuery.isError.value,
)
const loading = computed(
  () => snapshotQuery.isPending.value || integrationsQuery.isPending.value,
)
</script>

<template>
  <AppShell
    :snapshot="snapshot"
    :integrations="integrations"
    :offline="offline"
    :loading="loading"
  >
    <RouterView />
  </AppShell>
</template>
