<script setup lang="ts">
import type { TraceEvent } from '@/api/types'

defineProps<{ events: TraceEvent[] }>()
</script>

<template>
  <ol class="trace-timeline" aria-label="调度 trace">
    <li v-for="(event, index) in events" :key="`${event.at}-${index}`">
      <time>{{ event.at }}</time>
      <div>
        <strong>{{ event.title }}</strong>
        <p>{{ event.detail }}</p>
      </div>
    </li>
  </ol>
</template>
