<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { setupChildBridge } from './child-bridge'

interface Effect { kind: string; value?: number; duration?: number; target?: string }
interface Skill { name: string; description: string; cooldown: number; effects: Effect[] }
interface Servant {
  id: string; name: string; class: string; rarity: number; hp: number; attack: number; speed: number
  event_only: boolean; art_url: string; skill_art_url: string
  passives: { name: string; description: string }[]
  skills: Skill[]
  np: { name: string; card: string; target: string; multiplier: number; quote?: string; cg_url?: string; effects: Effect[] }
}
interface RosterItem { servant_id: string; level: number; np_level: number; shards: number; servant: Servant }
interface Template { id: string; name: string; description: string; skill_ids: string[] }
interface Payload {
  user_id: string
  profile: { quartz: number; qp: number; training_exp: number; team: string[]; master_template_id: string }
  roster: RosterItem[]
  catalogue: Servant[]
  master_templates: Template[]
  battle: null | { id: string; status: string }
}

const baseUrl = import.meta.env.BASE_URL
const adminMode = new URLSearchParams(location.search).get('mode') === 'admin'
const sessionTokenKey = adminMode ? 'chaldea-admin-ticket' : 'chaldea-player-ticket'
let targetRevision = 0
const token = ref('')
const loading = ref(true)
const pendingActions = ref(new Set<string>())
const error = ref('')
const notice = ref('')
const payload = ref<Payload | null>(null)
const selectedId = ref('')
const search = ref('')
const ownedOnly = ref(true)
const activeTab = ref<'roster' | 'team' | 'master' | 'admin'>('roster')
const teamDraft = ref<string[]>([])
const masterDraft = ref('')
const trainLevels = ref(1)
const targetUserId = ref('')
const grantResource = ref<'quartz' | 'qp' | 'training_exp'>('quartz')
const grantAmount = ref(100)
const grantReason = ref('管理员活动奖励')
const eventSearch = ref('')

const LEVEL_CAP = 80
const LEVEL_BONUS_MAX = 0.40
const insetSkillArtIds = new Set([
  'katsushika_hokusai_foreigner', 'cleopatra_assassin', 'senji_muramasa_saber',
  'musashi_saber', 'tamamo_no_mae_caster', 'kama_assassin', 'ryougi_shiki_assassin',
  'scathach_skadi_caster', 'semiramis_assassin', 'artoria_rhongomyniad_lancer',
  'okita_souji_saber', 'koyanskaya_light_assassin', 'solomon_grand_caster',
  'bb_moon_nurse_mooncancer', 'mash_decisive_shielder', 'minamoto_raikou_berserker',
  'nero_star_bride_beast', 'taira_kagekiyo_avenger', 'brynhild_lancer',
  'jeanne_archer_summer', 'ibuki_amano_murakumo_saber', 'melusine_lancer',
])

const ownedMap = computed(() => new Map(payload.value?.roster.map(item => [item.servant_id, item]) ?? []))
const selected = computed(() => payload.value?.catalogue.find(item => item.id === selectedId.value) ?? null)
const selectedOwned = computed(() => selected.value ? ownedMap.value.get(selected.value.id) : undefined)
const filtered = computed(() => {
  const needle = search.value.trim().toLowerCase()
  return (payload.value?.catalogue ?? []).filter(item => {
    if (ownedOnly.value && !ownedMap.value.has(item.id)) return false
    return !needle || `${item.name} ${item.id} ${item.class}`.toLowerCase().includes(needle)
  }).sort((a, b) => Number(ownedMap.value.has(b.id)) - Number(ownedMap.value.has(a.id)) || b.rarity - a.rarity)
})
const eventServants = computed(() => {
  const needle = eventSearch.value.trim().toLowerCase()
  return (payload.value?.catalogue ?? []).filter(item => item.event_only && (!needle || `${item.name} ${item.id} ${item.class}`.toLowerCase().includes(needle)))
})

function asset(path?: string) { return path ? `${baseUrl}${path}` : '' }
function stars(n: number) { return '★'.repeat(n) }
function trainedStat(base: number, level?: number) {
  const bounded = Math.max(1, Math.min(LEVEL_CAP, level ?? 1))
  return Math.round(base * (1 + LEVEL_BONUS_MAX * (bounded - 1) / (LEVEL_CAP - 1)))
}
function skillArtStyle(data: Servant, index: number): Record<string, string> {
  return {
    backgroundImage: `url(${asset(data.skill_art_url)})`,
    backgroundPosition: `${index * 50}% 50%`,
    backgroundSize: `${insetSkillArtIds.has(data.id) ? 360 : 300}% auto`,
  }
}
function effectText(effect: Effect) {
  const value = effect.value ? ` ${effect.value}${['heal', 'np_charge', 'np_drain', 'stars'].includes(effect.kind) ? '' : '%'}` : ''
  const duration = effect.duration && effect.duration < 90 ? ` / ${effect.duration}回合` : ''
  return `${effect.kind}${value}${duration}`
}
function uuid() { return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}` }
function isBusy(key: string) { return pendingActions.value.has(key) }
function setBusy(key: string, active: boolean) {
  const next = new Set(pendingActions.value)
  if (active) next.add(key)
  else next.delete(key)
  pendingActions.value = next
}

async function runAction<T>(key: string, action: () => Promise<T>): Promise<T | undefined> {
  if (isBusy(key)) return undefined
  setBusy(key, true)
  try { return await action() }
  finally { setBusy(key, false) }
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 15000)
  try {
    const response = await fetch(`${baseUrl}${path.replace(/^\//, '')}`, {
      ...options,
      signal: controller.signal,
      headers: { Authorization: `Bearer ${token.value}`, 'Content-Type': 'application/json', ...(options.headers ?? {}) },
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(body.detail || `请求失败 (${response.status})`)
    return body as T
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw new Error('请求超时，请稍后重试；页面其他操作仍可继续。')
    throw err
  } finally { window.clearTimeout(timeout) }
}

function syncDrafts() {
  teamDraft.value = [...(payload.value?.profile.team ?? [])]
  masterDraft.value = payload.value?.profile.master_template_id ?? ''
  if (!selectedId.value && payload.value?.roster.length) selectedId.value = payload.value.roster[0].servant_id
}

async function loadSelf() {
  payload.value = await api<Payload>('api/manage/me')
  syncDrafts()
}

async function loadTarget() {
  if (!/^\d{6,25}$/.test(targetUserId.value)) { error.value = '请输入数字 Discord 用户 ID'; return }
  const userId = targetUserId.value
  await runAction('load-player', async () => {
    error.value = ''; notice.value = ''
    try {
      const loaded = await refreshTarget(userId)
      if (loaded) notice.value = `已载入玩家 ${userId}`
    } catch (err) { error.value = err instanceof Error ? err.message : '载入失败' }
  })
}

async function refreshTarget(userId: string) {
  const revision = ++targetRevision
  const next = await api<Payload>(`api/admin/player/${userId}`)
  if (revision !== targetRevision || targetUserId.value !== userId) return false
  payload.value = next
  syncDrafts()
  return true
}

function toggleTeam(id: string) {
  if (!ownedMap.value.has(id)) return
  if (teamDraft.value.includes(id)) teamDraft.value = teamDraft.value.filter(item => item !== id)
  else if (teamDraft.value.length < 3) teamDraft.value.push(id)
  else notice.value = '队伍最多三名从者，请先移除一名。'
}

async function saveTeam() {
  await runAction('save-team', async () => {
    error.value = ''; notice.value = ''
    try {
      await api('api/manage/team', { method: 'POST', body: JSON.stringify({ servant_ids: teamDraft.value }) })
      await loadSelf(); notice.value = '出战队伍已保存。'
    } catch (err) { error.value = err instanceof Error ? err.message : '保存失败' }
  })
}

async function saveMaster() {
  await runAction('save-master', async () => {
    error.value = ''; notice.value = ''
    try {
      await api('api/manage/master-template', { method: 'POST', body: JSON.stringify({ template_id: masterDraft.value }) })
      await loadSelf(); notice.value = '御主模板已保存，将从下一场战斗生效。'
    } catch (err) { error.value = err instanceof Error ? err.message : '保存失败' }
  })
}

async function train() {
  if (!selected.value || !selectedOwned.value) return
  const key = `train:${selected.value.id}`
  await runAction(key, async () => {
    error.value = ''; notice.value = ''
    try {
      const result = await api<{ level: number; qp_cost: number; exp_cost: number }>('api/manage/train', { method: 'POST', body: JSON.stringify({ servant_id: selected.value?.id, levels: trainLevels.value }) })
      await loadSelf(); notice.value = `培养完成：Lv.${result.level}，消耗 ${result.qp_cost} QP / ${result.exp_cost} 经验。`
    } catch (err) { error.value = err instanceof Error ? err.message : '培养失败' }
  })
}

async function grant() {
  if (!payload.value) return
  const userId = payload.value.user_id
  await runAction('grant-resource', async () => {
    error.value = ''; notice.value = ''
    try {
      const result = await api<{ balance: number }>('api/admin/grant', { method: 'POST', body: JSON.stringify({ user_id: userId, resource: grantResource.value, amount: grantAmount.value, reason: grantReason.value, request_id: uuid() }) })
      await refreshTarget(userId); notice.value = `发放成功，当前余额 ${result.balance}。`
    } catch (err) { error.value = err instanceof Error ? err.message : '发放失败' }
  })
}

async function grantServant(id: string) {
  if (!payload.value) return
  const userId = payload.value.user_id
  await runAction(`grant-servant:${id}`, async () => {
    error.value = ''; notice.value = ''
    try {
      const result = await api<{ added: boolean; name: string }>('api/admin/servant', { method: 'POST', body: JSON.stringify({ user_id: userId, servant_id: id }) })
      await refreshTarget(userId); notice.value = result.added ? `已发放 ${result.name}。` : `玩家已拥有 ${result.name}。`
    } catch (err) { error.value = err instanceof Error ? err.message : '发放失败' }
  })
}

async function unlockStandard() {
  if (!payload.value || !confirm('确认补齐该玩家尚未拥有的全部常规英灵？活动英灵不会被发放。')) return
  const userId = payload.value.user_id
  await runAction('unlock-standard', async () => {
    error.value = ''; notice.value = ''
    try {
      const result = await api<{ added: number }>(`api/admin/unlock-standard/${userId}`, { method: 'POST' })
      await refreshTarget(userId); notice.value = `常规英灵补齐完成，本次新增 ${result.added} 名。`
    } catch (err) { error.value = err instanceof Error ? err.message : '解锁失败' }
  })
}

onMounted(async () => {
  const hash = new URLSearchParams(location.hash.replace(/^#/, ''))
  token.value = hash.get('ticket') ?? sessionStorage.getItem(sessionTokenKey) ?? ''
  if (hash.get('ticket')) {
    sessionStorage.setItem(sessionTokenKey, token.value)
    history.replaceState({}, document.title, `${location.pathname}${location.search}`)
  } else if (!token.value) {
    token.value = (await setupChildBridge())?.accessToken ?? ''
    if (token.value) sessionStorage.setItem(sessionTokenKey, token.value)
  }
  if (!token.value) { error.value = '请从 Discord 的迦勒底管理命令打开此页面。'; loading.value = false; return }
  try {
    if (adminMode) activeTab.value = 'admin'
    else await loadSelf()
  } catch (err) { error.value = err instanceof Error ? err.message : '载入失败' }
  finally { loading.value = false }
})
</script>

<template>
  <main class="mg-shell">
    <header class="mg-header">
      <div><span class="mg-kicker">CHALDEA CONTROL ROOM</span><h1>{{ adminMode ? '管理员控制台' : '个人迦勒底' }}</h1></div>
      <div v-if="payload" class="mg-resources"><span>圣晶石 <b>{{ payload.profile.quartz }}</b></span><span>QP <b>{{ payload.profile.qp }}</b></span><span>经验 <b>{{ payload.profile.training_exp }}</b></span></div>
    </header>

    <div v-if="loading" class="mg-state">正在连接迦勒底数据库…</div>
    <div v-if="error" class="mg-alert error">{{ error }} <button @click="error = ''">×</button></div>
    <div v-if="notice" class="mg-alert">{{ notice }} <button @click="notice = ''">×</button></div>

    <template v-if="!loading && !adminMode">
      <nav class="mg-tabs">
        <button :class="{ active: activeTab === 'roster' }" @click="activeTab = 'roster'">灵基一览</button>
        <button :class="{ active: activeTab === 'team' }" @click="activeTab = 'team'">出战编队</button>
        <button :class="{ active: activeTab === 'master' }" @click="activeTab = 'master'">御主模板</button>
      </nav>

      <section v-if="payload && activeTab !== 'master'" class="mg-workspace">
        <div class="mg-library">
          <div class="mg-toolbar"><input v-model="search" placeholder="搜索名称 / 职阶 / ID"><label><input v-model="ownedOnly" type="checkbox"> 仅已拥有</label></div>
          <div class="mg-grid">
            <article v-for="item in filtered" :key="item.id" :class="['mg-card', { selected: item.id === selectedId, locked: !ownedMap.has(item.id), inTeam: teamDraft.includes(item.id) }]" @click="selectedId = item.id">
              <span class="mg-stars">{{ stars(item.rarity) }}</span><span class="mg-class">{{ item.class }}</span>
              <img :src="asset(item.art_url)" :alt="item.name"><div><b>{{ item.name }}</b><small v-if="ownedMap.get(item.id)">Lv.{{ ownedMap.get(item.id)?.level }} · NP{{ ownedMap.get(item.id)?.np_level }}</small><small v-else>未召唤</small></div>
              <button v-if="activeTab === 'team' && ownedMap.has(item.id)" class="mg-team-toggle" @click.stop="toggleTeam(item.id)">{{ teamDraft.includes(item.id) ? '移出' : '编入' }}</button>
            </article>
          </div>
        </div>

        <aside v-if="selected" class="mg-detail">
          <img class="mg-detail-art" :src="asset(selected.art_url)" :alt="selected.name">
          <div class="mg-detail-head"><span>{{ stars(selected.rarity) }} · {{ selected.class }}</span><h2>{{ selected.name }}</h2><small>{{ selected.id }}</small></div>
          <div class="mg-statline"><span>HP <b>{{ trainedStat(selected.hp, selectedOwned?.level) }}</b><small v-if="selectedOwned && selectedOwned.level > 1">基础 {{ selected.hp }}</small></span><span>ATK <b>{{ trainedStat(selected.attack, selectedOwned?.level) }}</b><small v-if="selectedOwned && selectedOwned.level > 1">基础 {{ selected.attack }}</small></span><span>SPD <b>{{ selected.speed }}</b><small>固有速度</small></span></div>
          <section><h3>被动技能</h3><p v-for="passive in selected.passives" :key="passive.name"><b>{{ passive.name }}</b><br>{{ passive.description }}</p></section>
          <section><h3>保有技能</h3><div class="mg-skill-icons"><figure v-for="(skill, index) in selected.skills" :key="skill.name"><i :style="skillArtStyle(selected, index)"></i><figcaption>{{ skill.name }}</figcaption></figure></div><p v-for="skill in selected.skills" :key="skill.name"><b>{{ skill.name }}</b> · CT {{ skill.cooldown }}<br>{{ skill.description }}<small>{{ skill.effects.map(effectText).join(' · ') }}</small></p></section>
          <section><h3>宝具 · {{ selected.np.card }}</h3><img class="mg-cg" :src="asset(selected.np.cg_url)" :alt="selected.np.name"><p><b>{{ selected.np.name }}</b><br>{{ selected.np.quote }}<small>倍率 {{ selected.np.multiplier }}% · {{ selected.np.target === 'all' ? '敌方全体' : selected.np.target === 'team' ? '己方全体' : '敌方单体' }}</small></p></section>
          <div v-if="selectedOwned" class="mg-train"><select v-model.number="trainLevels"><option v-for="n in 10" :key="n" :value="n">提升 {{ n }} 级</option></select><button :disabled="isBusy(`train:${selected.id}`)" @click="train">{{ isBusy(`train:${selected.id}`) ? '处理中…' : '培养' }}</button></div>
        </aside>
      </section>

      <footer v-if="payload && activeTab === 'team'" class="mg-savebar"><span>已选择 {{ teamDraft.length }}/3：{{ teamDraft.map(id => payload?.catalogue.find(item => item.id === id)?.name).join('、') }}</span><button :disabled="isBusy('save-team') || teamDraft.length !== 3" @click="saveTeam">{{ isBusy('save-team') ? '保存中…' : '保存编队' }}</button></footer>

      <section v-if="payload && activeTab === 'master'" class="mg-template-grid">
        <article v-for="template in payload.master_templates" :key="template.id" :class="['mg-template', { selected: masterDraft === template.id }]" @click="masterDraft = template.id"><span>COMMAND SPELL</span><h2>{{ template.name }}</h2><p>{{ template.description }}</p><small>{{ template.skill_ids.join(' · ') }}</small></article>
        <footer class="mg-savebar"><span>所选模板将在下一场决斗生成随机魔术与陷阱。</span><button :disabled="isBusy('save-master') || !masterDraft" @click="saveMaster">{{ isBusy('save-master') ? '保存中…' : '保存模板' }}</button></footer>
      </section>
    </template>

    <template v-if="!loading && adminMode">
      <section class="mg-admin-search"><input v-model.trim="targetUserId" inputmode="numeric" placeholder="输入 Discord 用户 ID" @keyup.enter="loadTarget"><button :disabled="isBusy('load-player')" @click="loadTarget">{{ isBusy('load-player') ? '载入中…' : '载入玩家' }}</button></section>
      <section v-if="payload" class="mg-admin-grid">
        <article class="mg-admin-panel"><span class="mg-kicker">PLAYER</span><h2>{{ payload.user_id }}</h2><p>已拥有 {{ payload.roster.length }} 名从者 · 当前战斗 {{ payload.battle?.status ?? '无' }}</p><button :disabled="isBusy('unlock-standard')" @click="unlockStandard">{{ isBusy('unlock-standard') ? '补齐中…' : '补齐全部常规英灵' }}</button></article>
        <article class="mg-admin-panel"><span class="mg-kicker">RESOURCE GRANT</span><h2>发放资源</h2><select v-model="grantResource"><option value="quartz">圣晶石</option><option value="qp">QP</option><option value="training_exp">战斗经验</option></select><input v-model.number="grantAmount" type="number" min="1" max="10000000"><input v-model="grantReason" maxlength="255"><button :disabled="isBusy('grant-resource')" @click="grant">{{ isBusy('grant-resource') ? '发放中…' : '确认发放' }}</button></article>
        <article class="mg-admin-panel wide"><span class="mg-kicker">EVENT SERVANTS · {{ eventServants.length }}</span><h2>活动英灵发放</h2><input v-model="eventSearch" placeholder="不受 Discord 25 项限制，搜索全部活动英灵"><div class="mg-event-grid"><div v-for="item in eventServants" :key="item.id"><img :src="asset(item.art_url)" :alt="item.name"><span><b>{{ item.name }}</b><small>{{ stars(item.rarity) }} · {{ item.class }} · {{ item.id }}</small></span><button :disabled="isBusy(`grant-servant:${item.id}`) || ownedMap.has(item.id)" @click="grantServant(item.id)">{{ ownedMap.has(item.id) ? '已拥有' : isBusy(`grant-servant:${item.id}`) ? '发放中…' : '发放' }}</button></div></div></article>
      </section>
    </template>
  </main>
</template>

<style scoped>
:global(body){margin:0;background:#080c16;color:#edf3ff;font-family:Inter,"Noto Sans SC",system-ui,sans-serif;min-width:320px}:global(*){box-sizing:border-box}.mg-shell{min-height:100vh;padding:clamp(14px,2vw,30px);background:radial-gradient(circle at 18% 0,#182a4c 0,transparent 32%),radial-gradient(circle at 90% 15%,#341d3f 0,transparent 28%),#080c16}.mg-header{display:flex;align-items:end;justify-content:space-between;gap:20px;padding:20px 24px;border:1px solid #33476a;background:#0d1424d9;box-shadow:0 18px 60px #0007}.mg-header h1{margin:4px 0 0;font:700 clamp(28px,4vw,52px)/1.05 Georgia,serif;letter-spacing:.04em}.mg-kicker{color:#7cc7ff;font-size:11px;letter-spacing:.2em}.mg-resources{display:flex;gap:10px;flex-wrap:wrap}.mg-resources span{padding:9px 13px;border:1px solid #36537c;background:#111d32;border-radius:4px;font-size:12px}.mg-resources b{color:#ffe08c}.mg-state,.mg-alert{margin:18px 0;padding:14px 18px;border:1px solid #2e6c72;background:#102a30}.mg-alert.error{border-color:#8d3850;background:#33151f}.mg-alert button{float:right;border:0;background:none;color:inherit;font-size:20px}.mg-tabs{display:flex;gap:8px;margin:18px 0}.mg-tabs button,.mg-admin-search button,.mg-savebar button,.mg-train button,.mg-admin-panel button,.mg-team-toggle{border:1px solid #3f6091;background:#162640;color:#dcecff;padding:10px 18px;cursor:pointer}.mg-tabs button.active,.mg-savebar button,.mg-admin-search button{border-color:#79c8ff;background:linear-gradient(135deg,#1b5d91,#373d8d);box-shadow:0 0 22px #4ca8ff2b}.mg-workspace{display:grid;grid-template-columns:minmax(0,1fr) minmax(330px,420px);gap:18px;align-items:start}.mg-library,.mg-detail,.mg-template,.mg-admin-panel{border:1px solid #293b5a;background:#0d1424e8;box-shadow:0 20px 50px #0006}.mg-toolbar{display:flex;justify-content:space-between;gap:12px;padding:14px;border-bottom:1px solid #263b5f}.mg-toolbar input,.mg-admin-search input,.mg-admin-panel input,.mg-admin-panel select,.mg-train select{min-width:0;border:1px solid #355174;background:#090f1c;color:#eaf2ff;padding:11px 12px}.mg-toolbar>input{flex:1}.mg-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;padding:12px;max-height:calc(100vh - 220px);overflow:auto}.mg-card{position:relative;min-height:250px;overflow:hidden;border:1px solid #263a59;background:linear-gradient(#16233d,#0d1424);cursor:pointer}.mg-card.selected{border-color:#76c9ff;box-shadow:inset 0 0 0 1px #76c9ff,0 0 18px #54b8ff33}.mg-card.locked{filter:grayscale(.75);opacity:.58}.mg-card.inTeam{border-color:#e8c56b}.mg-card>img{width:100%;height:185px;object-fit:contain;object-position:center bottom;background:radial-gradient(circle at 50% 70%,#355c9066,transparent 65%)}.mg-card>div{padding:8px}.mg-card b,.mg-card small{display:block}.mg-card b{font-size:13px}.mg-card small{margin-top:4px;color:#93a8c7;font-size:11px}.mg-stars,.mg-class{position:absolute;z-index:2;top:6px;padding:3px 6px;background:#070b13c9;font-size:10px}.mg-stars{left:6px;color:#ffe48c}.mg-class{right:6px;color:#8fd2ff}.mg-team-toggle{position:absolute;right:6px;bottom:6px;padding:5px 8px;font-size:10px}.mg-detail{position:sticky;top:14px;max-height:calc(100vh - 28px);overflow:auto}.mg-detail-art{width:100%;height:42vh;min-height:300px;object-fit:contain;object-position:center bottom;background:radial-gradient(circle at 50% 68%,#243e6f,transparent 62%)}.mg-detail-head,.mg-detail section,.mg-statline,.mg-train{padding:14px 18px;border-top:1px solid #253957}.mg-detail-head span{color:#ffe08a}.mg-detail h2{margin:5px 0}.mg-detail h3{margin:0 0 10px;color:#8ccfff;font-size:13px;letter-spacing:.12em}.mg-detail p{color:#c4d0e1;font-size:12px;line-height:1.7}.mg-detail p small{display:block;color:#7f94b5}.mg-statline{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.mg-statline span{padding:8px;background:#111e33;font-size:11px}.mg-statline b{display:block;color:#fff1aa;font-size:16px}.mg-statline small{display:block;margin-top:3px;color:#7690b5;font-size:9px}.mg-skill-icons{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:8px 0 16px}.mg-skill-icons figure{min-width:0;margin:0;text-align:center}.mg-skill-icons i{display:block;width:min(92px,100%);aspect-ratio:1;margin:0 auto 7px;border:3px solid #e9c66e;border-radius:50%;background-color:#0b1425;background-repeat:no-repeat;box-shadow:inset 0 0 0 3px #10182bdd,0 5px 18px #0008}.mg-skill-icons figcaption{overflow:hidden;color:#cfe3ff;font-size:10px;line-height:1.35;text-overflow:ellipsis;white-space:nowrap}.mg-cg{width:100%;aspect-ratio:16/9;object-fit:cover}.mg-train{display:flex;gap:8px}.mg-train select{flex:1}.mg-template-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}.mg-template{padding:22px;cursor:pointer}.mg-template.selected{border-color:#ffda79;box-shadow:inset 0 0 28px #e8b94a1c}.mg-template span{font-size:10px;color:#7dc9ff;letter-spacing:.16em}.mg-template p{min-height:44px;color:#aabbd1}.mg-savebar{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 18px;border:1px solid #465e83;background:#111a2b;position:sticky;bottom:10px;z-index:10}.mg-admin-search{display:flex;gap:10px;margin:18px 0}.mg-admin-search input{flex:1;font-size:16px}.mg-admin-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.mg-admin-panel{padding:20px}.mg-admin-panel.wide{grid-column:1/-1}.mg-admin-panel input,.mg-admin-panel select{width:100%;margin:5px 0}.mg-event-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:8px;max-height:58vh;overflow:auto;margin-top:12px}.mg-event-grid>div{display:grid;grid-template-columns:70px 1fr auto;align-items:center;gap:10px;padding:8px;border:1px solid #273b5b;background:#111b2d}.mg-event-grid img{width:70px;height:82px;object-fit:contain}.mg-event-grid small{display:block;color:#8499b9;font-size:10px;margin-top:4px}button:disabled{opacity:.45;cursor:not-allowed}@media(max-width:850px){.mg-header{align-items:start;flex-direction:column}.mg-workspace{grid-template-columns:1fr}.mg-grid{max-height:none;grid-template-columns:repeat(2,minmax(0,1fr))}.mg-detail{position:relative;top:auto;max-height:none}.mg-admin-grid{grid-template-columns:1fr}.mg-admin-panel.wide{grid-column:auto}.mg-event-grid{grid-template-columns:1fr}.mg-savebar{flex-direction:column;align-items:stretch}.mg-savebar button{width:100%}}@media(max-width:420px){.mg-shell{padding:8px}.mg-header{padding:15px}.mg-card{min-height:218px}.mg-card>img{height:155px}.mg-toolbar{align-items:stretch;flex-direction:column}.mg-detail-art{height:360px}.mg-event-grid>div{grid-template-columns:56px 1fr auto}.mg-event-grid img{width:56px;height:72px}}
</style>
