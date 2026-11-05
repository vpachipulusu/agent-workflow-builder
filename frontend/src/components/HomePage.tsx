import { useEffect, useState } from 'react'
import { listAgents, listWorkflows } from '../api/client'

export default function HomePage() {
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
        自然言語でAIエージェントとワークフローのコードを自動生成。
        Microsoft Agent Framework の Skills を活用し、対話的にコードを作成・編集・テストできます。
      </p>

      <div className="grid-home">
        <div className="card">
          <div className="card-title">🤖 エージェント</div>
          <p className="stat-value">{agentCount}</p>
          <p className="stat-label">作成済みエージェント</p>
        </div>
        <div className="card">
          <div className="card-title">🔀 ワークフロー</div>
          <p className="stat-value">{workflowCount}</p>
          <p className="stat-label">作成済みワークフロー</p>
        </div>
      </div>

      <div className="card" style={{ marginTop: 24, maxWidth: 680 }}>
        <div className="card-title" style={{ marginBottom: 12 }}>アーキテクチャ</div>
        <pre className="code-block">{`
┌─────────────────────────────────────────┐
│          Frontend (React + TS)          │
│  ┌────────────┐  ┌───────────────────┐  │
│  │ Agent作成   │  │ Workflow作成       │  │
│  │ (NL/手動)  │  │ (NL/手動/編集)    │  │
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
