import { useEffect, useState } from 'react'
import { useI18n } from '../i18n/LanguageContext'
import { listAgents, listWorkflows } from '../api/client'

export default function HomePage() {
  const { t } = useI18n()
  const [agentCount, setAgentCount] = useState(0)
  const [workflowCount, setWorkflowCount] = useState(0)

  useEffect(() => {
    listAgents().then(d => setAgentCount(d.agents.length)).catch(() => {})
    listWorkflows().then(d => setWorkflowCount(d.workflows.length)).catch(() => {})
  }, [])

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Microsoft Agent Framework Code Builder</h1>
      </div>

      <p style={{ color: 'var(--text-secondary)', marginBottom: 32, maxWidth: 680, lineHeight: 1.7, fontSize: 14 }}>
        {t.home.intro}
      </p>

      <div className="grid-home">
        <div className="card">
          <div className="card-title">🤖 {t.home.agents}</div>
          <p className="stat-value">{agentCount}</p>
          <p className="stat-label">{t.home.agentsCreated}</p>
        </div>
        <div className="card">
          <div className="card-title">🔀 {t.home.workflows}</div>
          <p className="stat-value">{workflowCount}</p>
          <p className="stat-label">{t.home.workflowsCreated}</p>
        </div>
      </div>

      <div className="card" style={{ marginTop: 24, maxWidth: 680 }}>
        <div className="card-title" style={{ marginBottom: 12 }}>{t.home.architecture}</div>
        <pre className="code-block">{`
┌─────────────────────────────────────────┐
│          Frontend (React + TS)          │
│  ┌────────────┐  ┌───────────────────┐  │
${t.home.diagramRow1}
${t.home.diagramRow2}
│  └─────┬──────┘  └────────┬──────────┘  │
└────────┼──────────────────┼─────────────┘
         │  REST API        │
┌────────┼──────────────────┼─────────────┐
│        ▼                  ▼             │
│  ┌────────────────────────────────┐     │
│  │      Orchestrator Agent        │     │
│  │  (Azure OpenAI GPT-4o)        │     │
│  └──────┬──────────────┬─────────┘     │
│         │              │               │
│  ┌──────▼─────┐ ┌──────▼──────────┐   │
│  │ agent-     │ │ workflow-       │   │
│  │ creator    │ │ creator         │   │
│  │ Skill      │ │ Skill           │   │
│  │ ┌────────┐ │ │ ┌────────────┐  │   │
│  │ │SKILL.md│ │ │ │SKILL.md    │  │   │
│  │ │scripts/│ │ │ │scripts/    │  │   │
│  │ │refs/   │ │ │ │refs/       │  │   │
│  │ └────────┘ │ │ └────────────┘  │   │
│  └────────────┘ └─────────────────┘   │
│        Backend (FastAPI)               │
└────────────────────────────────────────┘
        `.trim()}</pre>
      </div>
    </div>
  )
}
