<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { setupChildBridge } from './child-bridge'

interface Effect { kind: string; value?: number; remaining?: number }
interface Combatant {
  slot: number
  servant_id: string
  hp: number
  max_hp: number
  np: number
  stars: number
  cooldowns: number[]
  buffs: Effect[]
  debuffs: Effect[]
}
interface Card { id: string; servant_slot: number; servant_id: string; type: 'B' | 'A' | 'Q' }
interface Skill { name: string; description: string; cooldown: number }
interface Servant {
  id: string
  name: string
  class: string
  rarity: number
  hp: number
  attack: number
  skills: Skill[]
  np: { name: string; card: string; target: string }
  art_url: string | null
  skill_art_url: string | null
  released: boolean
}
interface BattleState {
  match_id: string
  status: 'active' | 'finished'
  turn: number
  winner_id: string | null
  teams: Record<string, Combatant[]>
  log: string[]
}
interface BattlePayload {
  id: string
  status: string
  state: BattleState
  player_id: string
  opponent_id: string
  hand: Card[]
  catalogue: Record<string, Servant>
}

const baseUrl = import.meta.env.BASE_URL
const loading = ref(true)
const error = ref('')
const waiting = ref(false)
const payload = ref<BattlePayload | null>(null)
const selectedCards = ref<string[]>([])
const selectedSkill = ref<{ servant_slot: number; skill_index: number } | null>(null)
const selectedNp = ref<number | null>(null)
const accessToken = ref<string | null>(null)
let pollTimer: number | null = null
let observedTurn = 0

const state = computed(() => payload.value?.state ?? null)
const playerId = computed(() => payload.value?.player_id ?? '')
const myTeam = computed(() => state.value?.teams[playerId.value] ?? [])
const enemyTeam = computed(() => {
  if (!state.value || !payload.value) return []
  return state.value.teams[payload.value.opponent_id] ?? []
})
const requiredCards = computed(() => selectedNp.value === null ? 3 : 2)
const canSubmit = computed(() =>
  state.value?.status === 'active' &&
  selectedCards.value.length === requiredCards.value &&
  !waiting.value,
)
const recentLog = computed(() => (state.value?.log ?? []).slice(-8).reverse())

function servant(member: Combatant): Servant {
  return payload.value!.catalogue[member.servant_id]
}

function hpPercent(member: Combatant): number {
  return Math.max(0, Math.round(member.hp / member.max_hp * 100))
}

function assetUrl(path: string): string {
  return baseUrl + path.replace(/^\//, '')
}

function skillStyle(data: Servant, index: number): Record<string, string> {
  if (!data.skill_art_url) return {}
  return {
    backgroundImage: `url(${assetUrl(data.skill_art_url)})`,
    backgroundPosition: `${index * 50}% 50%`,
  }
}

function effectLabel(effect: Effect): string {
  const labels: Record<string, string> = {
    attack_up: '攻击↑', defense_up: '防御↑', card_up_b: 'Buster↑',
    card_up_a: 'Arts↑', card_up_q: 'Quick↑', card_up_all: '全卡↑',
    evade: '回避', invincible: '无敌', taunt: '嘲讽', guts: '战续',
    attack_down: '攻击↓', defense_down: '防御↓', stun: '眩晕',
    poison: '毒', burn: '灼烧', regen: '再生', damage_cut: '减伤',
  }
  return labels[effect.kind] || effect.kind
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (!accessToken.value) throw new Error('未获得 Discord 身份令牌，请从机器人命令打开战斗。')
  const response = await fetch(baseUrl + path.replace(/^\//, ''), {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken.value}`,
      ...(options.headers || {}),
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(body.detail || `请求失败 (${response.status})`)
  }
  return response.json()
}

async function refresh(silent = false) {
  try {
    const next = await api<BattlePayload>('api/battle/state')
    payload.value = next
    if (next.state.turn !== observedTurn) {
      observedTurn = next.state.turn
      selectedCards.value = []
      selectedSkill.value = null
      selectedNp.value = null
      waiting.value = false
    }
    error.value = ''
  } catch (err) {
    if (!silent) error.value = err instanceof Error ? err.message : '无法载入战斗'
  } finally {
    loading.value = false
  }
}

function toggleCard(cardId: string) {
  if (waiting.value) return
  const existing = selectedCards.value.indexOf(cardId)
  if (existing >= 0) {
    selectedCards.value.splice(existing, 1)
  } else if (selectedCards.value.length < requiredCards.value) {
    selectedCards.value.push(cardId)
  }
}

function toggleSkill(servantSlot: number, skillIndex: number) {
  const member = myTeam.value[servantSlot]
  if (!member || member.hp <= 0 || member.cooldowns[skillIndex] > 0 || waiting.value) return
  const current = selectedSkill.value
  selectedSkill.value = current?.servant_slot === servantSlot && current.skill_index === skillIndex
    ? null
    : { servant_slot: servantSlot, skill_index: skillIndex }
}

function toggleNp(slot: number) {
  const member = myTeam.value[slot]
  if (!member || member.hp <= 0 || member.np < 100 || waiting.value) return
  selectedNp.value = selectedNp.value === slot ? null : slot
  selectedCards.value = selectedCards.value.slice(0, selectedNp.value === null ? 3 : 2)
}

async function submitAction() {
  if (!payload.value || !canSubmit.value) return
  waiting.value = true
  error.value = ''
  try {
    const result = await api<{ resolved: boolean; state: BattleState }>('api/battle/action', {
      method: 'POST',
      body: JSON.stringify({
        battle_id: payload.value.id,
        cards: selectedCards.value,
        skill: selectedSkill.value,
        np_servant_slot: selectedNp.value,
      }),
    })
    if (result.resolved) {
      await refresh(true)
    }
  } catch (err) {
    waiting.value = false
    error.value = err instanceof Error ? err.message : '行动提交失败'
  }
}

onMounted(async () => {
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const browserTicket = hash.get('ticket')
  if (browserTicket) {
    accessToken.value = browserTicket
    window.history.replaceState({}, document.title, window.location.pathname)
  } else {
    const bridge = await setupChildBridge()
    accessToken.value = bridge?.accessToken ?? null
  }
  if (!accessToken.value) {
    loading.value = false
    error.value = '请在 Discord 中使用 /迦勒底 战斗 获取专属入口。'
    return
  }
  await refresh()
  pollTimer = window.setInterval(() => refresh(true), 1800)
})

onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearInterval(pollTimer)
})
</script>

<template>
  <main class="battle-shell">
    <div class="ambient ambient-one"></div>
    <div class="ambient ambient-two"></div>

    <section v-if="loading" class="center-state">
      <div class="chaldea-mark">C</div>
      <p>正在建立灵子演算连接…</p>
    </section>

    <section v-else-if="error && !payload" class="center-state error-state">
      <div class="chaldea-mark">!</div>
      <h1>连接未完成</h1>
      <p>{{ error }}</p>
    </section>

    <template v-else-if="payload && state">
      <header class="battle-header glass-panel">
        <div>
          <span class="eyebrow">CHALDEA COMBAT SIMULATION</span>
          <h1>灵基演算战</h1>
        </div>
        <div class="turn-chip">
          <span>TURN</span>
          <strong>{{ state.turn }}</strong>
        </div>
        <div class="status-chip" :class="state.status">
          {{ state.status === 'active' ? (waiting ? '等待对手' : '行动选择') : '战斗结束' }}
        </div>
      </header>

      <section class="arena">
        <div class="team-zone enemy-zone">
          <div class="zone-label"><span>ENEMY</span><small>{{ payload.opponent_id }}</small></div>
          <div class="servant-line">
            <article v-for="member in enemyTeam" :key="member.slot" class="servant-card enemy" :class="{ defeated: member.hp <= 0 }">
              <div class="portrait" :data-class="servant(member).class">
                <span class="class-name">{{ servant(member).class }}</span>
                <img v-if="servant(member).art_url" :src="assetUrl(servant(member).art_url!)" :alt="servant(member).name" loading="lazy" />
                <strong v-else>{{ servant(member).name.slice(0, 1) }}</strong>
                <span class="rarity">{{ '★'.repeat(servant(member).rarity) }}</span>
              </div>
              <div class="servant-info">
                <h2>{{ servant(member).name }}</h2>
                <div class="bar hp"><i :style="{ width: hpPercent(member) + '%' }"></i></div>
                <div class="numbers"><span>{{ member.hp }} / {{ member.max_hp }}</span><span>NP {{ member.np }}%</span></div>
                <div class="effects"><span v-for="effect in [...member.buffs, ...member.debuffs]" :key="effect.kind + effect.remaining">{{ effectLabel(effect) }}</span></div>
              </div>
            </article>
          </div>
        </div>

        <div class="versus-line"><span></span><b>VS</b><span></span></div>

        <div class="team-zone ally-zone">
          <div class="zone-label"><span>YOUR PARTY</span><small>{{ payload.player_id }}</small></div>
          <div class="servant-line">
            <article v-for="member in myTeam" :key="member.slot" class="servant-card ally" :class="{ defeated: member.hp <= 0 }">
              <div class="portrait" :data-class="servant(member).class">
                <span class="class-name">{{ servant(member).class }}</span>
                <img v-if="servant(member).art_url" :src="assetUrl(servant(member).art_url!)" :alt="servant(member).name" loading="eager" />
                <strong v-else>{{ servant(member).name.slice(0, 1) }}</strong>
                <span class="rarity">{{ '★'.repeat(servant(member).rarity) }}</span>
              </div>
              <div class="servant-info">
                <h2>{{ servant(member).name }}</h2>
                <div class="bar hp"><i :style="{ width: hpPercent(member) + '%' }"></i></div>
                <div class="bar np"><i :style="{ width: member.np + '%' }"></i></div>
                <div class="numbers"><span>{{ member.hp }} HP</span><span>NP {{ member.np }}%</span></div>
                <div class="skill-row">
                  <button
                    v-for="(skill, index) in servant(member).skills"
                    :key="skill.name"
                    class="skill-button"
                    :class="{ selected: selectedSkill?.servant_slot === member.slot && selectedSkill.skill_index === index, 'has-art': Boolean(servant(member).skill_art_url) }"
                    :style="skillStyle(servant(member), index)"
                    :disabled="member.hp <= 0 || member.cooldowns[index] > 0 || waiting"
                    :title="skill.description"
                    @click="toggleSkill(member.slot, index)"
                  >
                    <span v-if="!servant(member).skill_art_url">{{ index + 1 }}</span>
                    <small v-if="member.cooldowns[index]">{{ member.cooldowns[index] }}</small>
                  </button>
                  <button class="np-button" :class="{ ready: member.np >= 100, selected: selectedNp === member.slot }" :disabled="member.np < 100 || member.hp <= 0 || waiting" @click="toggleNp(member.slot)">NP</button>
                </div>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section v-if="state.status === 'active'" class="command-deck glass-panel">
        <div class="command-heading">
          <div><span class="eyebrow">COMMAND SPELL</span><h2>选择 {{ requiredCards }} 张指令卡</h2></div>
          <div class="selection-count">{{ selectedCards.length }} / {{ requiredCards }}</div>
        </div>
        <div class="cards-row">
          <button
            v-for="card in payload.hand"
            :key="card.id"
            class="command-card"
            :class="['type-' + card.type.toLowerCase(), { selected: selectedCards.includes(card.id) }]"
            :disabled="waiting || (!selectedCards.includes(card.id) && selectedCards.length >= requiredCards)"
            @click="toggleCard(card.id)"
          >
            <span class="card-order">{{ selectedCards.indexOf(card.id) >= 0 ? selectedCards.indexOf(card.id) + 1 : '' }}</span>
            <b>{{ card.type }}</b>
            <small>{{ servant(myTeam[card.servant_slot]).name }}</small>
          </button>
        </div>
        <div class="action-row">
          <p v-if="error" class="inline-error">{{ error }}</p>
          <p v-else-if="waiting" class="waiting-copy">行动已锁定，等待对手回应…</p>
          <p v-else class="hint-copy">技能每回合最多使用一次；宝具会占用一个指令位。</p>
          <button class="attack-button" :disabled="!canSubmit" @click="submitAction">
            <span>{{ waiting ? 'LOCKED' : 'ATTACK' }}</span>
            <small>{{ waiting ? '等待同步' : '锁定行动' }}</small>
          </button>
        </div>
      </section>

      <section v-else class="result-panel glass-panel">
        <span class="eyebrow">BATTLE FINISHED</span>
        <h2>{{ state.winner_id === payload.player_id ? '演算胜利' : state.winner_id ? '演算败北' : '平局' }}</h2>
        <p>战斗结果已经写入服务器记录。</p>
      </section>

      <aside class="battle-log glass-panel">
        <span class="eyebrow">COMBAT LOG</span>
        <p v-for="(line, index) in recentLog" :key="index">{{ line }}</p>
      </aside>
    </template>
  </main>
</template>
