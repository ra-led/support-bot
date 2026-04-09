import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const parseHosts = (value?: string) =>
  (value || '')
    .split(',')
    .map((host) => host.trim())
    .filter(Boolean)

const allowedHosts = Array.from(
  new Set([
    ...parseHosts(process.env.VITE_ALLOWED_HOSTS),
    ...parseHosts(process.env.SERVICE_FQDN_NGINX)
  ])
)

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    allowedHosts
  }
})
