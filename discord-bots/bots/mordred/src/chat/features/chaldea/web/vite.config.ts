import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/chaldea/',
  plugins: [vue()],
  server: {
    host: true,
    port: 3005,
    hmr: false,
    proxy: {
      '/chaldea/api': {
        target: 'http://127.0.0.1:8005',
        rewrite: (path) => path.replace(/^\/chaldea/, ''),
        changeOrigin: true,
      },
    },
  },
})

