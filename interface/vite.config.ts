import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// En développement, les appels /api et /hors-ligne vont au service Python (uvicorn sur le port 8000).
export default defineConfig({
  plugins: [react()],
  // numéro de version : chaque mise en ligne a son propre cache dans le navigateur (l'ancien est effacé)
  define: { __VERSION__: JSON.stringify(Date.now().toString(36)) },
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/hors-ligne': 'http://127.0.0.1:8000' } },
  build: { chunkSizeWarningLimit: 1100, rollupOptions: { output: { manualChunks: { carto: ['maplibre-gl'] } } } },
})
