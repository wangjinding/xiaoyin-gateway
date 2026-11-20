<template>
  <!-- 侧栏：桌面常驻在左边，窄屏放进抽屉 —— 两处共用这一份，菜单项只维护一处 -->
  <div class="rail-inner">
    <div class="brand">
      <span class="logo"><Icon name="bolt" :size="17" /></span>
      <div>
        <b>{{ t('nav.title') }}</b>
        <span>{{ apiHost }}</span>
      </div>
    </div>

    <nav class="nav">
      <template v-for="(g, gi) in groups" :key="g.id">
        <div v-if="gi > 0" class="nav-sep" />
        <router-link
          v-for="m in g.items"
          :key="m.path"
          :to="m.path"
          class="nav-i"
          :class="{ on: isActive(m.path) }"
          @click="emit('navigate')"
        >
          <Icon :name="m.icon" :size="18" />
          <span>{{ t(`nav.menu${m.key}`) }}</span>
          <!-- 用户反馈待办数（未处理 + 处理中）。只有管理员能看到这一项，非管理员请求会 403，
               这里静默不显示，不打扰。 -->
          <span v-if="m.key === 'feedbackinbox'" class="nav-badge"
                :title="t('nav.feedbackTodoTip', { n: todoCount })">{{ todoCount > 99 ? '99+' : todoCount }}</span>
        </router-link>
      </template>
    </nav>
  </div>
</template>

<script setup lang="ts">
const apiHost = location.host
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '../components/Icon.vue'
import { api } from '../api'
import type { NavGroup } from '../lib/nav'

// 第二十二轮：删掉侧栏底部那两行（「B · 素白蓝紫」+「v2.4.0 · 控制台」）。
// 皮肤名在设置页「外观与语言」和顶栏调色盘里都能看到，版本号也没必要常驻占位。
const props = defineProps<{ groups: NavGroup[] }>()
const emit = defineEmits<{ (e: 'navigate'): void }>()
const { t } = useI18n()
const route = useRoute()

// 用前缀匹配：/users 的子页（若有）也能让菜单高亮
function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(path + '/')
}
void props

// ── 用户反馈待办数（未处理 + 处理中）──────────────────────────────────────
//   2026-10-30（老板）：菜单上要显示待办数量。
//   模块级 ref：桌面侧栏和手机抽屉是两个组件实例，共用同一份数字，只轮询一次。
const todoCount = ref(0)
let todoTimer: ReturnType<typeof setInterval> | null = null

async function loadTodo() {
  try {
    const j = await api('/feedback/pending-count')
    todoCount.value = Number(j && j.total) || 0
  } catch {
    // 非管理员（403）或未登录 → 不显示徽标，不报错
    todoCount.value = 0
  }
}

onMounted(() => {
  loadTodo()
  todoTimer = setInterval(loadTodo, 30_000)
})
onUnmounted(() => {
  if (todoTimer) { clearInterval(todoTimer); todoTimer = null }
})
</script>

<style scoped>
.rail-inner {
  display: flex; flex-direction: column; height: 100%;
  background: var(--surface); padding: 14px 12px; overflow: hidden;
}
.brand { display: flex; align-items: center; gap: 10px; padding: 2px 8px 12px; }
/* 菜单项右侧的待办红点：贴在文字后面靠右，不挤图标 */
.nav-badge {
  margin-left: auto;
  min-width: 18px; height: 18px; padding: 0 5px;
  border-radius: 9px;
  background: #ef4444; color: #fff;
  font-size: 11px; font-weight: 600; line-height: 18px;
  text-align: center; font-variant-numeric: tabular-nums;
  box-shadow: 0 0 0 2px var(--surface);
}
.logo {
  width: 32px; height: 32px; border-radius: 10px; background: var(--primary);
  color: var(--primary-ink); display: grid; place-items: center; flex: none;
}
.brand b { font-size: 15px; display: block; line-height: 1.25; color: var(--text); }
.brand span { font-size: 11px; color: var(--muted-2); }
.nav { display: flex; flex-direction: column; gap: 1px; overflow-y: auto; flex: 1; }
.nav-i {
  display: flex; align-items: center; gap: 10px;
  /* 第二十三轮追加（老板先「缩短一点让滚动条不要出现」，再「上下间距可以大一点」）：
     行距随窗口高度自适应 —— 窗口高就宽松、窗口矮就收紧，两边都满足：
     下限 7px（行高 32px，与上一版一致，矮窗口不会顶出滚动条）、上限 11px（行高 40px，比原来 9px/36px 更松）。
     换算：600px 视口 ≈ 35px 行高、720px ≈ 38px、1080px 及以上封顶 40px；
     不滚动的下限：窗口高约 505px（yaml 那份固定值 36px 时是 ~605px 就会滚）。 */
  padding: clamp(7px, 1.4vh, 11px) 10px;
  border-radius: 10px; color: var(--muted); font-size: 13.5px;
  cursor: pointer; text-decoration: none; transition: background .15s, color .15s;
}
.nav-i:hover { background: var(--chip); color: var(--text); }
.nav-i.on { background: var(--primary-soft); color: var(--primary); font-weight: 600; }
.nav-sep { height: 1px; background: var(--line-2); margin: clamp(7px, 1.2vh, 13px) 8px; flex: none; }
</style>
