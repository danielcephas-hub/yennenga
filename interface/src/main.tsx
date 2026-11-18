import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import App from './App.tsx'

// connexions lentes ou coupées : dès la première visite, l'application et ses données sont gardées dans le navigateur
// (enregistré tout de suite, sans attendre la fin du chargement : le préchargement commence aussitôt)
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  navigator.serviceWorker.register(`/sw.js?v=${__VERSION__}`).catch(() => undefined)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
