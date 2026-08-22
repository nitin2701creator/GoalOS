import { useState, useEffect } from 'react'
import {
  getIntegration,
  getMaskedCredentials,
  saveCredentials,
  testConnection,
  connectIntegration,
  disconnectIntegration,
  type IntegrationDetail,
  type MaskedCredential,
} from '../lib/api'

interface Props {
  slug: string
  onClose: () => void
  onSaved: () => void
}

export default function ConfigModal({ slug, onClose, onSaved }: Props) {
  const [detail, setDetail] = useState<IntegrationDetail | null>(null)
  const [masked, setMasked] = useState<MaskedCredential[]>([])
  const [values, setValues] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    loadData()
  }, [slug])

  const loadData = async () => {
    setLoading(true)
    try {
      const [d, m] = await Promise.all([getIntegration(slug), getMaskedCredentials(slug)])
      setDetail(d)
      setMasked(m)
      setValues({})
    } catch (err: any) {
      setMsg(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setMsg('')
    try {
      const toSave: Record<string, string> = {}
      for (const [key, val] of Object.entries(values)) {
        if (val && val !== '') toSave[key] = val
      }
      if (Object.keys(toSave).length === 0) {
        setMsg('No changes to save')
        setSaving(false)
        return
      }
      await saveCredentials(slug, toSave)
      setMsg('✅ Credentials saved successfully')
      await loadData()
    } catch (err: any) {
      setMsg(`❌ ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    setMsg('')
    try {
      const res = await testConnection(slug)
      setTestResult(res)
      setMsg(res.success ? '✅ Connection successful' : `❌ ${res.message}`)
    } catch (err: any) {
      setTestResult({ success: false, message: err.message })
      setMsg(`❌ ${err.message}`)
    } finally {
      setTesting(false)
    }
  }

  const handleConnect = async () => {
    setMsg('')
    try {
      const res = await connectIntegration(slug)
      if (res.redirect_url) {
        window.open(res.redirect_url, '_blank', 'width=600,height=700')
        setMsg('OAuth window opened — complete authorization there')
      } else {
        setMsg(res.message || 'Use the credential fields below to configure')
      }
    } catch (err: any) {
      setMsg(`❌ ${err.message}`)
    }
  }

  const handleDisconnect = async () => {
    if (!confirm('Disconnect this integration? All stored credentials will be removed.')) return
    try {
      await disconnectIntegration(slug)
      setMsg('✅ Disconnected')
      onSaved()
    } catch (err: any) {
      setMsg(`❌ ${err.message}`)
    }
  }

  if (loading) {
    return (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
        <div className="bg-white rounded-xl p-8 text-gray-500">Loading...</div>
      </div>
    )
  }

  if (!detail) {
    return (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
        <div className="bg-white rounded-xl p-8 text-red-500">{msg || 'Integration not found'}</div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-5 border-b border-gray-200 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">{detail.icon}</span>
            <div>
              <h2 className="text-lg font-bold text-gray-900">{detail.name}</h2>
              <p className="text-sm text-gray-500">{detail.description}</p>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
        </div>

        {/* Status */}
        <div className="px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <span className={`w-3 h-3 rounded-full ${
              detail.status === 'connected' ? 'bg-green-500' :
              detail.status === 'configured' ? 'bg-yellow-500' :
              detail.status === 'error' ? 'bg-red-500' : 'bg-gray-400'
            }`}></span>
            <span className="text-sm font-medium capitalize">{detail.status.replace('_', ' ')}</span>
            {detail.last_connected_at && (
              <span className="text-xs text-gray-400 ml-2">
                Last connected: {new Date(detail.last_connected_at).toLocaleString()}
              </span>
            )}
          </div>
          {detail.error_message && (
            <p className="text-sm text-red-500 mt-2">{detail.error_message}</p>
          )}
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-5">
          {/* OAuth button */}
          {detail.has_oauth && (
            <button
              onClick={handleConnect}
              className="w-full py-3 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold transition flex items-center justify-center gap-2"
            >
              🔗 Connect with {detail.name}
            </button>
          )}

          {/* Credential fields */}
          {detail.credential_fields.length > 0 && (
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Credentials</h3>
              {detail.credential_fields.map(field => {
                const m = masked.find(x => x.key === field.key)
                return (
                  <div key={field.key}>
                    <label className="block text-sm font-medium text-gray-600 mb-1">
                      {field.label}
                      {field.required && <span className="text-red-400 ml-1">*</span>}
                    </label>
                    <input
                      type={field.type === 'password' ? 'password' : field.type === 'url' ? 'url' : 'text'}
                      value={values[field.key] || ''}
                      onChange={e => setValues({ ...values, [field.key]: e.target.value })}
                      placeholder={m?.is_set ? m.masked_value : `Enter ${field.label.toLowerCase()}`}
                      className="w-full px-3 py-2 rounded-lg border border-gray-300 focus:border-blue-500 focus:outline-none text-sm"
                    />
                    {m?.is_set && !values[field.key] && (
                      <p className="text-xs text-gray-400 mt-1">Currently set (leave empty to keep)</p>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex gap-3">
            {detail.credential_fields.length > 0 && (
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex-1 py-2.5 rounded-lg bg-green-600 hover:bg-green-700 text-white font-medium transition disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save Credentials'}
              </button>
            )}
            <button
              onClick={handleTest}
              disabled={testing}
              className="flex-1 py-2.5 rounded-lg bg-gray-600 hover:bg-gray-700 text-white font-medium transition disabled:opacity-50"
            >
              {testing ? 'Testing...' : '🧪 Test Connection'}
            </button>
          </div>

          {/* Test result */}
          {testResult && (
            <div className={`p-3 rounded-lg text-sm ${
              testResult.success
                ? 'bg-green-50 text-green-700 border border-green-200'
                : 'bg-red-50 text-red-700 border border-red-200'
            }`}>
              {testResult.success ? '✅' : '❌'} {testResult.message}
            </div>
          )}

          {/* Messages */}
          {msg && !testResult && (
            <div className="text-sm text-gray-600 bg-gray-50 p-3 rounded-lg">{msg}</div>
          )}

          {/* Disconnect */}
          {detail.status !== 'not_configured' && (
            <button
              onClick={handleDisconnect}
              className="w-full py-2.5 rounded-lg border border-red-300 text-red-600 hover:bg-red-50 font-medium transition text-sm"
            >
              Disconnect
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
