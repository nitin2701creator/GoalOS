import type { IntegrationSummary } from '../lib/api'

interface Props {
  integration: IntegrationSummary
  statusColor: string
  statusLabel: string
  onClick: () => void
}

export default function IntegrationCard({ integration, statusColor, statusLabel, onClick }: Props) {
  return (
    <div
      onClick={onClick}
      className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 cursor-pointer hover:shadow-md hover:border-blue-300 transition-all"
    >
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className="text-3xl">{integration.icon}</span>
          <div>
            <h3 className="font-semibold text-gray-900">{integration.name}</h3>
            <p className="text-xs text-gray-500 capitalize">{integration.auth_type.replace('_', ' ')}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-2.5 h-2.5 rounded-full ${statusColor}`}></span>
          <span className="text-xs text-gray-500">{statusLabel}</span>
        </div>
      </div>
      <p className="text-sm text-gray-600 mb-4 line-clamp-2">{integration.description}</p>
      <div className="flex items-center justify-between">
        {integration.last_connected_at && (
          <span className="text-xs text-gray-400">
            Last: {new Date(integration.last_connected_at).toLocaleDateString()}
          </span>
        )}
        {integration.error_message && (
          <span className="text-xs text-red-500 truncate ml-auto max-w-[200px]" title={integration.error_message}>
            {integration.error_message}
          </span>
        )}
        <button className="text-sm text-blue-600 hover:text-blue-800 font-medium ml-auto">
          Configure →
        </button>
      </div>
    </div>
  )
}
