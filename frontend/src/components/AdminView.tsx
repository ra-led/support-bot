import { useEffect, useState } from 'react'
import { fetchStats } from '../api'

interface StatsResponse {
  total_requests: number
  by_status: Record<string, number>
}

export default function AdminView() {
  const [stats, setStats] = useState<StatsResponse | null>(null)

  useEffect(() => {
    fetchStats().then(setStats)
  }, [])

  return (
    <div>
      <h2>Admin Statistics</h2>
      <p className="tag">Separated admin view</p>
      <div className="stat-grid">
        <div className="stat-card">
          <h3>Total requests</h3>
          <p>{stats?.total_requests ?? 0}</p>
        </div>
        {stats &&
          Object.entries(stats.by_status).map(([status, count]) => (
            <div className="stat-card" key={status}>
              <h3>{status}</h3>
              <p>{count}</p>
            </div>
          ))}
      </div>
    </div>
  )
}
