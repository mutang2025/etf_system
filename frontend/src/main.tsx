import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ScannerProvider } from './services/scannerContext'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ScannerProvider>
        <App />
      </ScannerProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
