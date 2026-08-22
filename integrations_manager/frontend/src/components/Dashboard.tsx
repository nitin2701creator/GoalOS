import { useState, useEffect } from 'react'
import { listIntegrations, type IntegrationSummary } from '../lib/api'
import IntegrationCard from './IntegrationCard'
import ConfigModal from './ConfigModal'

interface Props {
  onLogout: () => void
}

const STATUS_COLORS: Record<string, string> = {
  not_configured: 'bg-gray-500',
  configured: 'bg-yellow-500',
  connected: 'bg-green-500',
  error: 'bg-red-500',
}

const STATUS_LABELS: Record<string, string> = {
  not_configured: 'Not Configured',
  configured: 'Configured',
  connected: 'Connected',
  error: 'Error',
}

export default function Dashboard({ onLogout }: Props) {
  const [integrations, setIntegrations] = useState<IntegrationSummary[]>([])
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = async () => {
    try {
      const data = await listIntegrations()
      setIntegrations(data)
    } catch (err) {
      console.error('Failed to load integrations:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const connected = integrations.filter(i => i.status === 'connected').length
  const total = integrations.length

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-3xl">⚙️</span>
            <div>
              <h1 className="text-xl font-bold text-gray-900">GoalOS Integrations</h1>
              <p className="text-sm text-gray-500">Connect and manage external services used by GoalOS.</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-gray-500">
              <span className="font-semibold text-green-600">{connected}</span>/{total} connected
            </span>
            <button
              onClick={onLogout}
              className="text-sm text-gray-500 hover:text-gray-700 transition"
            >
              Sign Out
            </button>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        {loading ? (
          <div className="text-center py-20 text-gray-400">Loading integrations...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {integrations.map(integ => (
              <IntegrationCard
                key={integ.slug}
                integration={integ}
                statusColor={STATUS_COLORS[integ.status] || 'bg-gray-500'}
                statusLabel={STATUS_LABELS[integ.status] || integ.status}
                onClick={() => setSelectedSlug(integ.slug)}
              />
            ))}
          </div>
        )}
      </main>

      {/* Config modal */}
      {selectedSlug && (
        <ConfigModal
          slug={selectedSlug}
          onClose={() => setSelectedSlug(null)}
          onSaved={() => {
            setSelectedSlug(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}
