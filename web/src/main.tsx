import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './styles.css'

/**
 * Offline support, so a reviewer on a plane or an auditor on a locked-down
 * network can still read a bundle.
 *
 * Registered after load rather than during it: a service worker competing with
 * the first render for bandwidth makes the page slower for everyone in order to
 * help the minority who are offline.
 *
 * Failure is silent on purpose. A browser with service workers disabled, or a
 * page served over plain HTTP, should get the ordinary online dashboard rather
 * than an error about a feature it never asked for.
 */
function registerOfflineSupport() {
  if (!('serviceWorker' in navigator)) return
  window.addEventListener('load', () => {
    navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`).catch(() => {
      /* no offline support here; the dashboard still works online */
    })
  })
}

registerOfflineSupport()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
