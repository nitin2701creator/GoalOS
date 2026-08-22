import { useState, useEffect } from 'react'
import { isAuthenticated, login, clearAuth } from './lib/api'
import LoginPage from './components/LoginPage'
import Dashboard from './components/Dashboard'

export default function App() {
  const [authed, setAuthed] = useState(isAuthenticated())

  const handleLogin = async (username: string, password: string) => {
    await login(username, password)
    setAuthed(true)
  }

  const handleLogout = () => {
    clearAuth()
    setAuthed(false)
  }

  if (!authed) {
    return <LoginPage onLogin={handleLogin} />
  }

  return <Dashboard onLogout={handleLogout} />
}
