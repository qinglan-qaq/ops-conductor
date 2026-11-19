<script setup lang="ts">
import type { PlayerStatus } from './useRunPlayer'

defineProps<{
  status: PlayerStatus
  speed: 1 | 2 | 4
  progress: number
  cursor: number
  total: number
  showAll: boolean
  follow: boolean
}>()

const emit = defineEmits<{
  (event: 'toggle'): void
  (event: 'prev'): void
  (event: 'next'): void
  (event: 'replay'): void
  (event: 'speed', value: 1 | 2 | 4): void
  (event: 'toggle-show-all'): void
  (event: 'toggle-follow'): void
}>()

function onSpeedChange(event: Event): void {
  const value = Number((event.target as HTMLSelectElement).value)
  emit('speed', value as 1 | 2 | 4)
}
</script>

<template>
  <section class="run-controls" aria-label="回放控制" data-run-controls>
    <div class="run-control-buttons">
      <button
        class="button button-primary"
        type="button"
        data-player-toggle
        :aria-label="status === 'playing' ? '暂停回放' : '播放回放'"
        @click="emit('toggle')"
      >
        {{ status === 'playing' ? '暂停' : status === 'finished' ? '重播' : '播放' }}
      </button>
      <button class="button button-quiet" type="button" data-player-prev aria-label="上一步" @click="emit('prev')">
        上一步
      </button>
      <button class="button button-quiet" type="button" data-player-next aria-label="下一步" @click="emit('next')">
        下一步
      </button>
      <button class="text-button" type="button" data-player-replay aria-label="从头重播" @click="emit('replay')">
        重播
      </button>
      <label class="run-speed">
        倍速
        <select :value="speed" aria-label="播放倍速" @change="onSpeedChange">
          <option :value="1">1x</option>
          <option :value="2">2x</option>
          <option :value="4">4x</option>
        </select>
      </label>
      <button
        class="text-button"
        type="button"
        data-player-show-all
        :aria-pressed="showAll"
        @click="emit('toggle-show-all')"
      >
        {{ showAll ? '返回回放' : '完整视图' }}
      </button>
      <button
        class="text-button"
        type="button"
        data-player-follow
        :aria-pressed="follow"
        @click="emit('toggle-follow')"
      >
        {{ follow ? '跟随：开' : '跟随：关' }}
      </button>
    </div>
    <div class="run-progress">
      <div
        class="run-progress-track"
        role="progressbar"
        aria-label="回放进度"
        :aria-valuemin="0"
        :aria-valuemax="total"
        :aria-valuenow="cursor"
      >
        <span class="run-progress-fill" :style="{ width: `${Math.round(progress * 100)}%` }" />
      </div>
      <span class="mono run-progress-label">{{ cursor }} / {{ total }}</span>
    </div>
    <details class="run-shortcuts">
      <summary>快捷键</summary>
      <p>空格 播放/暂停 · ←/→ 单步 · R 重播 · 1/2/4 倍速</p>
    </details>
  </section>
</template>
