<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { SalesAnalytics } from '@/api/types'

const props = defineProps<{ sales: SalesAnalytics }>()

const chartWidth = ref(640)
const chartHeight = 230
const chartShell = ref<HTMLDivElement | null>(null)
let resizeObserver: ResizeObserver | null = null

const padding = { left: 54, right: 18, top: 18, bottom: 38 }
const innerWidth = computed(
  () => chartWidth.value - padding.left - padding.right,
)
const innerHeight = chartHeight - padding.top - padding.bottom
const baseY = chartHeight - padding.bottom

const maxValue = computed(() => {
  const values = props.sales.points.map((point) => point.amount_usd)
  const max = Math.max(...values, props.sales.daily_target_usd, 1)
  return Math.ceil(max / 5_000) * 5_000
})

const points = computed(() => {
  const count = props.sales.points.length
  return props.sales.points.map((point, index) => ({
    ...point,
    x:
      count <= 1
        ? padding.left + innerWidth.value / 2
        : padding.left + (index / (count - 1)) * innerWidth.value,
    y:
      padding.top +
      innerHeight * (1 - point.amount_usd / maxValue.value),
  }))
})

const linePath = computed(() =>
  points.value
    .map(
      (point, index) =>
        `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`,
    )
    .join(' '),
)

const areaPath = computed(() => {
  const first = points.value[0]
  const last = points.value[points.value.length - 1]
  if (!first || !last) return ''
  return `${linePath.value} L ${last.x.toFixed(1)} ${baseY} L ${first.x.toFixed(1)} ${baseY} Z`
})

const targetY = computed(
  () =>
    padding.top +
    innerHeight * (1 - props.sales.daily_target_usd / maxValue.value),
)

const ticks = computed(() =>
  [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const value = maxValue.value * ratio
    return {
      value,
      y: padding.top + innerHeight * (1 - ratio),
      label: formatCompact(value),
    }
  }),
)

const achievement = computed(() =>
  props.sales.target_usd
    ? ((props.sales.total_usd / props.sales.target_usd) * 100).toFixed(1)
    : '0.0',
)

function formatCompact(value: number): string {
  if (value >= 1_000) return `$${Math.round(value / 1_000)}k`
  return `$${Math.round(value)}`
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString('zh-CN')}`
}

onMounted(() => {
  if (typeof ResizeObserver === 'undefined' || !chartShell.value) return
  resizeObserver = new ResizeObserver((entries) => {
    const width = Math.round(entries[0]?.contentRect.width ?? 0)
    if (width > 0) {
      chartWidth.value = Math.max(280, width)
    }
  })
  resizeObserver.observe(chartShell.value)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <section class="panel chart-panel" data-sales-chart>
    <header class="chart-head">
      <div>
        <p class="panel-kicker">销售额</p>
        <h2>近 7 日走势</h2>
      </div>
      <div class="chart-summary">
        <strong class="mono">{{ formatMoney(sales.total_usd) }}</strong>
        <span class="mono">/ {{ formatMoney(sales.target_usd) }}</span>
        <em>{{ achievement }}% 周目标</em>
      </div>
    </header>

    <div v-if="points.length" ref="chartShell" class="sales-chart-shell">
      <svg
        class="sales-chart"
        :viewBox="`0 0 ${chartWidth} ${chartHeight}`"
        role="img"
        aria-labelledby="sales-chart-title sales-chart-desc"
      >
        <title id="sales-chart-title">近 7 日销售额与日目标</title>
        <desc id="sales-chart-desc">
          每日销售额柱状折线，最后一天为最高点；金色虚线为日目标
          {{ formatMoney(sales.daily_target_usd) }}。
        </desc>

        <g class="chart-grid">
          <template v-for="tick in ticks" :key="tick.y">
            <line
              :x1="padding.left"
              :x2="chartWidth - padding.right"
              :y1="tick.y"
              :y2="tick.y"
            />
            <text
              :x="padding.left - 8"
              :y="tick.y + 3"
              text-anchor="end"
            >
              {{ tick.label }}
            </text>
          </template>
        </g>

        <line
          class="target-line"
          :x1="padding.left"
          :x2="chartWidth - padding.right"
          :y1="targetY"
          :y2="targetY"
        />
        <text
          class="target-label"
          :x="padding.left + 4"
          :y="targetY - 6"
          text-anchor="start"
        >
          日目标 {{ formatMoney(sales.daily_target_usd) }}
        </text>

        <path class="sales-area" :d="areaPath" />
        <path class="sales-line" :d="linePath" />

        <g
          v-for="(point, index) in points"
          :key="point.date"
          class="sales-point"
          :class="{ 'is-last': index === points.length - 1 }"
          :data-sales-point="point.date"
        >
          <title>{{ point.date }} · {{ formatMoney(point.amount_usd) }}</title>
          <circle :cx="point.x" :cy="point.y" r="4" />
          <text
            :x="point.x"
            :y="chartHeight - 14"
            text-anchor="middle"
          >
            {{ point.date }}
          </text>
          <text
            v-if="index === points.length - 1"
            class="point-value"
            :x="point.x"
            :y="point.y - 10"
            text-anchor="end"
          >
            {{ formatMoney(point.amount_usd) }}
          </text>
        </g>
      </svg>
    </div>
    <p v-else class="empty-state">暂无销售额数据。</p>
  </section>
</template>
