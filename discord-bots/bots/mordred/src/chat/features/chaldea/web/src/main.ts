import { createApp } from 'vue'
import BattleApp from './BattleApp.vue'
import ManagementApp from './ManagementApp.vue'
import './style.css'

const mode = new URLSearchParams(window.location.search).get('mode')
createApp(mode === 'manage' || mode === 'admin' ? ManagementApp : BattleApp).mount('#app')
