import react from '@vitejs/plugin-react'
import { defineConfig, searchForWorkspaceRoot } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // API_URL permet de viser un autre backend (ex. API_URL=http://localhost:8001 npm run dev).
      '/api': process.env.API_URL ?? 'http://localhost:8000',
    },
    fs: {
      // Les exemples sont importés depuis ../datasets (hors du dossier frontend).
      allow: [searchForWorkspaceRoot(process.cwd()), '../datasets'],
    },
  },
})
