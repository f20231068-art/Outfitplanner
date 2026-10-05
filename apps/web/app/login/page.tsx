'use client'

import { useRouter } from 'next/navigation'
import { FormEvent, useEffect, useState } from 'react'
import { ApiError, login, refreshSession, register } from '../../lib/api'

export default function LoginPage() {
  const router = useRouter()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // already signed in (the refresh cookie is still valid)? go straight to the app
  useEffect(() => {
    refreshSession().then((ok) => ok && router.replace('/'))
  }, [router])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await (mode === 'login' ? login : register)(email, password)
      router.replace('/')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
      setBusy(false)
    }
  }

  return (
    <main className="auth">
      <form className="auth-card" onSubmit={submit} noValidate>
        <div>
          <h1>Outfitmaxxing</h1>
          <p className="sub">Menswear outfits from Indian stores, matched to your budget.</p>
        </div>
        <h2 style={{ fontSize: '1.1rem' }}>{mode === 'login' ? 'Log in' : 'Create an account'}</h2>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <div className="field">
          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {mode === 'register' && <span className="hint">At least 10 characters.</span>}
        </div>
        <button className="btn" type="submit" disabled={busy || !email || !password}>
          {busy ? 'One moment…' : mode === 'login' ? 'Log in' : 'Sign up'}
        </button>
        <p className="sub">
          {mode === 'login' ? 'New here? ' : 'Already have an account? '}
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login')
              setError(null)
            }}
          >
            {mode === 'login' ? 'Create an account' : 'Log in'}
          </button>
        </p>
      </form>
    </main>
  )
}
