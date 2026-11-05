import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge as FlowEdge,
  MarkerType,
  Position,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useNavigate } from 'react-router-dom'

import {
  createWorkflowFromPrompt,
  editWorkflow,
  listWorkflows,
  getWorkflow,
  deleteWorkflow,
  runWorkflow,
  type WorkflowCreateResponse,
  type WorkflowDefinition,
  type WorkflowEvent,
} from '../api/client'

type ViewTab = 'graph' | 'yaml' | 'code'
type ExecutionStatus = 'idle' | 'running' | 'done' | 'error'

interface StepLog {
  id: number
  type: string
  node?: string
  input?: string
  output?: string
  source?: string
  target?: string
  condition?: string
  timestamp: number
}

interface BuilderMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  workflowResult?: WorkflowCreateResponse | null
}

// This workflow really changes Azure resources, so it has its own protected page;
// the open API used here refuses to edit or run it.
const WEEKEND_SAVER = 'weekend_saver'

export default function WorkflowBuilderPage() {
  const navigate = useNavigate()
  const [workflows, setWorkflows] = useState<{ name: string; description: string; executors_count: number; edges_count: number }[]>([])
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<WorkflowCreateResponse | null>(null)
  const [selectedWf, setSelectedWf] = useState<{ name: string; definition: any; code: string } | null>(null)
  const [viewTab, setViewTab] = useState<ViewTab>('graph')

  // ── Builder chat state ──
  const [builderMessages, setBuilderMessages] = useState<BuilderMessage[]>([])
  const [builderInput, setBuilderInput] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const builderEndRef = useRef<HTMLDivElement>(null)

  // ── Playground state ──
  const [runInput, setRunInput] = useState('')
  const [execStatus, setExecStatus] = useState<ExecutionStatus>('idle')
  const [logs, setLogs] = useState<StepLog[]>([])
  const [activeNodes, setActiveNodes] = useState<Record<string, 'processing' | 'completed' | 'idle'>>({})
  const [activeEdges, setActiveEdges] = useState<Record<string, 'flowing' | 'done' | 'idle'>>({})
  const [nodeOutputs, setNodeOutputs] = useState<Record<string, string>>({})
  const logsEndRef = useRef<HTMLDivElement>(null)

  // ── Resizable split ──
  const [chatPanelPct, setChatPanelPct] = useState(33)
  const centerRef = useRef<HTMLDivElement>(null)
  const isDragging = useRef(false)

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDragging.current = true
    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current || !centerRef.current) return
      const rect = centerRef.current.getBoundingClientRect()
      const pct = ((ev.clientY - rect.top) / rect.height) * 100
      setChatPanelPct(Math.min(80, Math.max(15, pct)))
    }
    const onUp = () => {
      isDragging.current = false
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [])

  // ── Log detail popup ──
  const [selectedLog, setSelectedLog] = useState<StepLog | null>(null)

  const refreshList = () => {
    listWorkflows().then(d => setWorkflows(d.workflows)).catch(() => {})
  }

  useEffect(() => { refreshList() }, [])

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  useEffect(() => {
    builderEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [builderMessages, loading])

  // ── New creation ──
  const handleNew = () => {
    setIsCreating(true)
    setBuilderMessages([{
      role: 'system',
      content: '新しいワークフローを作成します。どんなワークフローを作りたいですか？説明してください。',
    }])
    setResult(null)
    setSelectedWf(null)
    resetExecution()
    setBuilderInput('')
  }

  // ── Builder chat send ──
  const handleBuilderSend = async () => {
    if (!builderInput.trim() || loading) return
    const userMsg: BuilderMessage = { role: 'user', content: builderInput.trim() }
    setBuilderMessages(prev => [...prev, userMsg])
    setBuilderInput('')
    setLoading(true)

    const currentName = result?.name || selectedWf?.name

    try {
      let res: WorkflowCreateResponse
      if (!currentName) {
        res = await createWorkflowFromPrompt(userMsg.content)
      } else {
        res = await editWorkflow(currentName, userMsg.content)
      }

      setResult(res)
      if (res.name) {
        const data = await getWorkflow(res.name)
        setSelectedWf(data)
      }
      resetExecution()
      refreshList()

      const action = currentName ? '更新' : '作成'
      const assistantMsg: BuilderMessage = {
        role: 'assistant',
        content: res.validation.valid
          ? `✅ ワークフロー「${res.name}」を${action}しました。\n\n引き続きチャットで修正できます。例：\n• 「ログ記録ステップを追加して」\n• 「条件分岐を変更して」\n• 「新しいノードを追加して」`
          : `⚠️ ワークフロー「${res.name}」を${action}しましたが、バリデーションエラーがあります：\n${res.validation.errors.join('\n')}`,
        workflowResult: res,
      }
      setBuilderMessages(prev => [...prev, assistantMsg])
    } catch (e: any) {
      setBuilderMessages(prev => [...prev, {
        role: 'assistant',
        content: `❌ エラーが発生しました: ${e.message}`,
      }])
    } finally {
      setLoading(false)
    }
  }

  // ── Edit selected workflow via chat ──
  const handleEditSelectedWf = () => {
    if (!selectedWf && !result) return
    const name = result?.name || selectedWf?.name
    setIsCreating(true)
    setBuilderMessages([{
      role: 'system',
      content: `ワークフロー「${name}」を編集モードで開きました。どのように変更しますか？`,
    }])
    setBuilderInput('')
  }

  const handleSelectWf = async (name: string) => {
    if (name === WEEKEND_SAVER) {
      navigate('/weekend-saver')
      return
    }
    try {
      const data = await getWorkflow(name)
      setSelectedWf(data)
      setResult(null)
      setIsCreating(false)
      setBuilderMessages([])
      resetExecution()
    } catch {}
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`ワークフロー "${name}" を削除しますか？`)) return
    await deleteWorkflow(name)
    setSelectedWf(null)
    setResult(null)
    setIsCreating(false)
    setBuilderMessages([])
    resetExecution()
    refreshList()
  }

  // ── Playground execution ──
  const resetExecution = () => {
    setLogs([])
    setActiveNodes({})
    setActiveEdges({})
    setNodeOutputs({})
    setExecStatus('idle')
  }

  const activeDef: WorkflowDefinition | null = result?.definition ?? selectedWf?.definition ?? null
  const activeCode: string = result?.code ?? selectedWf?.code ?? ''
  const activeName: string = result?.name ?? selectedWf?.name ?? ''

  const handleRun = async () => {
    if (!activeName || execStatus === 'running') return
    resetExecution()
    setExecStatus('running')
    const message = runInput.trim() || 'Hello, start the workflow!'

    await runWorkflow(activeName, message, (event: WorkflowEvent) => {
      const timestamp = Date.now()
      switch (event.type) {
        case 'start':
          setLogs(prev => [...prev, { id: prev.length, type: 'start', timestamp }])
          break
        case 'node_enter':
          setActiveNodes(prev => ({ ...prev, [event.node!]: 'processing' }))
          setLogs(prev => [...prev, { id: prev.length, type: 'node_enter', node: event.node, input: event.input, timestamp }])
          break
        case 'node_complete':
          setActiveNodes(prev => ({ ...prev, [event.node!]: 'completed' }))
          setNodeOutputs(prev => ({ ...prev, [event.node!]: event.output || '' }))
          setLogs(prev => [...prev, { id: prev.length, type: 'node_complete', node: event.node, output: event.output, timestamp }])
          break
        case 'edge_active': {
          const edgeKey = `${event.source}->${event.target}`
          setActiveEdges(prev => ({ ...prev, [edgeKey]: 'flowing' }))
          const conditionText = event.condition ? ` (条件: ${event.condition})` : ''
          setLogs(prev => [...prev, { id: prev.length, type: 'edge_active', source: event.source, target: event.target, condition: conditionText, timestamp }])
          setTimeout(() => { setActiveEdges(prev => ({ ...prev, [edgeKey]: 'done' })) }, 800)
          break
        }
        case 'edge_skipped': {
          setLogs(prev => [...prev, { id: prev.length, type: 'edge_skipped', source: event.source, target: event.target, condition: event.condition ? ` (条件: ${event.condition})` : '', timestamp }])
          break
        }
        case 'done':
          setExecStatus('done')
          setLogs(prev => [...prev, { id: prev.length, type: 'done', timestamp }])
          break
        case 'error':
          setExecStatus('error')
          setLogs(prev => [...prev, { id: prev.length, type: 'error', output: event.content, timestamp }])
          break
      }
    })
  }

  return (
    <div className="devui-shell">
      {/* ── Top Toolbar ── */}
      <div className="devui-toolbar">
        <div className="devui-toolbar-title">🔀 ワークフロー</div>
        <div style={{ flex: 1 }} />
        <div className="devui-toolbar-actions">
          <button className="btn btn-primary btn-sm" onClick={handleNew}>
            ＋ 新規作成
          </button>
        </div>
      </div>

      {/* ── Three-column body ── */}
      <div className="devui-body">
        {/* Left: Workflow list */}
        <div className="devui-list-panel">
          <div className="devui-list-header">
            <span className="devui-list-header-title">ワークフロー</span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{workflows.length}</span>
          </div>
          <div className="devui-list-body">
            {workflows.length === 0 ? (
              <div className="devui-empty">
                <div className="devui-empty-icon">🔀</div>
                <span>まだなし</span>
              </div>
            ) : (
              workflows.map(w => (
                <div
                  key={w.name}
                  className={`devui-list-item ${selectedWf?.name === w.name ? 'devui-list-item--active' : ''}`}
                  onClick={() => handleSelectWf(w.name)}
                >
                  <div className="devui-list-item-name">{w.name}</div>
                  <div className="devui-list-item-desc">{w.description}</div>
                  <div className="devui-list-item-meta">{w.executors_count} nodes · {w.edges_count} edges</div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Center: Builder Chat + Graph / Code / YAML */}
        <div className="devui-center" ref={centerRef}>
          {/* Builder Chat (creation / edit mode) — resizable top panel */}
          {isCreating && (
            <div className="builder-chat-panel" style={{ flex: `0 0 ${chatPanelPct}%`, maxHeight: `${chatPanelPct}%`, minHeight: 0, borderBottom: '2px solid rgba(99,102,241,0.3)' }}>
              <div className="builder-chat-header">
                <span className="builder-chat-header-title">💬 ワークフロー作成チャット</span>
                <button className="btn btn-secondary btn-sm" onClick={() => setIsCreating(false)}>
                  ✕ 閉じる
                </button>
              </div>
              <div className="builder-chat-messages">
                {builderMessages.map((msg, i) => (
                  <div key={i} className={`builder-msg builder-msg-${msg.role}`}>
                    <div className="builder-msg-role">
                      {msg.role === 'user' && '👤 あなた'}
                      {msg.role === 'assistant' && '🤖 AI'}
                      {msg.role === 'system' && '🔧 システム'}
                    </div>
                    <div className="builder-msg-content">{msg.content}</div>
                  </div>
                ))}
                {loading && (
                  <div className="builder-msg builder-msg-assistant">
                    <div className="builder-msg-role">🤖 AI</div>
                    <div className="builder-msg-content">
                      <span className="playground-thinking">生成中...</span>
                    </div>
                  </div>
                )}
                <div ref={builderEndRef} />
              </div>
              <div className="builder-chat-footer">
                <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
                  <textarea
                    className="form-input chat-textarea"
                    placeholder={result?.name || selectedWf?.name ? '修正内容を入力... (例: 「ログ記録ステップを追加して」)' : 'ワークフローの説明を入力...'}
                    value={builderInput}
                    onChange={e => setBuilderInput(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                        e.preventDefault()
                        handleBuilderSend()
                      }
                    }}
                    disabled={loading}
                    rows={2}
                    style={{ flex: 1, padding: '10px 14px', fontSize: 13 }}
                  />
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={handleBuilderSend}
                    disabled={loading || !builderInput.trim()}
                    style={{ alignSelf: 'flex-end', marginBottom: 2 }}
                  >
                    {loading ? <span className="spinner" /> : '送信'}
                  </button>
                </div>
                <div className="chat-textarea-hint">Ctrl+Enter で送信</div>
              </div>
            </div>
          )}

          {/* Drag handle */}
          {isCreating && (
            <div className="resize-handle-h" onMouseDown={handleDragStart} />
          )}

          {/* Workflow detail (graph/YAML/code) — shown below chat or full */}
          {activeDef ? (
            <div className="devui-center-full">
              <div className="devui-center-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>{activeName}</span>
                  {result?.validation && (
                    <span className={`badge ${result.validation.valid ? 'badge-success' : 'badge-error'}`}>
                      {result.validation.valid ? '✓ OK' : '✗ Error'}
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  <div className="devui-tabs tabs">
                    <button className={`tab ${viewTab === 'graph' ? 'active' : ''}`} onClick={() => setViewTab('graph')}>
                      📊 グラフ
                    </button>
                    <button className={`tab ${viewTab === 'yaml' ? 'active' : ''}`} onClick={() => setViewTab('yaml')}>
                      YAML
                    </button>
                    <button className={`tab ${viewTab === 'code' ? 'active' : ''}`} onClick={() => setViewTab('code')}>
                      Python
                    </button>
                  </div>
                  {!isCreating && (
                    <button className="btn btn-accent btn-sm" onClick={handleEditSelectedWf}>
                      ✏️ チャットで編集
                    </button>
                  )}
                  <button className="btn btn-danger btn-sm" onClick={() => handleDelete(activeName)}>
                    🗑️
                  </button>
                </div>
              </div>

              {result?.validation && !result.validation.valid && (
                <div style={{ padding: '8px 16px', background: 'var(--error-glow)', borderBottom: '1px solid var(--border)' }}>
                  {result.validation.errors.map((e, i) => (
                    <p key={i} style={{ color: 'var(--error)', fontSize: 12 }}>• {e}</p>
                  ))}
                </div>
              )}

              <div className="devui-center-body">
                {viewTab === 'graph' && (
                  <AnimatedWorkflowGraph
                    definition={activeDef}
                    activeNodes={activeNodes}
                    activeEdges={activeEdges}
                    nodeOutputs={nodeOutputs}
                  />
                )}
                {viewTab === 'yaml' && (
                  <pre className="code-block">{JSON.stringify(activeDef, null, 2)}</pre>
                )}
                {viewTab === 'code' && (
                  <pre className="code-block">{activeCode}</pre>
                )}
              </div>
            </div>
          ) : !isCreating ? (
            <div className="devui-empty">
              <div className="devui-empty-icon">📊</div>
              <span>ワークフローを作成または選択してください</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                「＋ 新規作成」ボタンか、左のリストからワークフローを選んでください
              </span>
            </div>
          ) : (
            <div className="devui-center-full" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>チャットでワークフローの説明を入力してください</span>
            </div>
          )}
        </div>

        {/* Right: Playground (execution) */}
        <div className="devui-right">
          <div className="devui-right-header">
            <span className="devui-right-header-title">🎮 プレイグラウンド</span>
            {execStatus !== 'idle' && (
              <button className="btn btn-secondary btn-sm" onClick={resetExecution}>リセット</button>
            )}
          </div>

          {activeName ? (
            <>
              {/* Run input */}
              <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
                  <textarea
                    className="form-input chat-textarea"
                    placeholder="入力メッセージ..."
                    value={runInput}
                    onChange={e => setRunInput(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                        e.preventDefault()
                        handleRun()
                      }
                    }}
                    disabled={execStatus === 'running'}
                    rows={2}
                    style={{ flex: 1, padding: '8px 12px', fontSize: 13 }}
                  />
                  <button
                    className={`btn btn-sm ${execStatus === 'running' ? 'btn-secondary' : 'btn-primary'}`}
                    onClick={handleRun}
                    disabled={execStatus === 'running'}
                    style={{ alignSelf: 'flex-end', marginBottom: 2 }}
                  >
                    {execStatus === 'running' ? <><span className="spinner" /> 実行中</> : '▶ 実行'}
                  </button>
                </div>
                <div className="chat-textarea-hint">Ctrl+Enter で送信</div>
              </div>

              {/* Status */}
              {execStatus !== 'idle' && (
                <div style={{ padding: '0 12px', flexShrink: 0, marginTop: 8 }}>
                  <div className={`playground-wf-status playground-wf-status-${execStatus}`}>
                    {execStatus === 'running' && '⏳ 実行中...'}
                    {execStatus === 'done' && '✅ 完了'}
                    {execStatus === 'error' && '❌ エラー'}
                  </div>
                </div>
              )}

              {/* Logs */}
              <div className="devui-right-body">
                {logs.length === 0 && execStatus === 'idle' && (
                  <div className="devui-empty">
                    <span style={{ fontSize: 12 }}>▶ 実行ボタンでワークフローをテスト</span>
                  </div>
                )}
                {logs.length > 0 && (
                  <div className="devui-exec-section">
                    <div className="devui-exec-section-title">📋 実行ログ</div>
                    <div className="wf-log-list">
                      {logs.map(log => (
                        <div key={log.id} className={`wf-log-item wf-log-${log.type} wf-log-clickable`} onClick={() => setSelectedLog(log)}>
                          <div className="wf-log-badge">
                            {log.type === 'start' && '🟢 開始'}
                            {log.type === 'node_enter' && '⏩ 実行中'}
                            {log.type === 'node_complete' && '✅ 完了'}
                            {log.type === 'edge_active' && '→ 転送'}
                            {log.type === 'edge_skipped' && '⊘ スキップ'}
                            {log.type === 'done' && '🏁 終了'}
                            {log.type === 'error' && '❌ エラー'}
                          </div>
                          {log.node && <div className="wf-log-node">{log.node}</div>}
                          {log.type === 'edge_active' && <div className="wf-log-edge">{log.source} → {log.target}{log.condition || ''}</div>}
                          {log.type === 'edge_skipped' && <div className="wf-log-edge" style={{opacity: 0.5, textDecoration: 'line-through'}}>{log.source} → {log.target}{log.condition || ''}</div>}
                          {log.input && (
                            <div className="wf-log-data">
                              <span className="wf-log-data-label">入力:</span>
                              {log.input.length > 100 ? log.input.slice(0, 100) + '...' : log.input}
                            </div>
                          )}
                          {log.output && (
                            <div className="wf-log-data">
                              <span className="wf-log-data-label">出力:</span>
                              {log.output.length > 150 ? log.output.slice(0, 150) + '...' : log.output}
                            </div>
                          )}
                          <div className="wf-log-tap-hint">タップで詳細</div>
                        </div>
                      ))}
                      <div ref={logsEndRef} />
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="devui-empty">
              <div className="devui-empty-icon">🎮</div>
              <span>ワークフローを選択して実行</span>
            </div>
          )}
        </div>
      </div>

      {/* Log Detail Popup */}
      {selectedLog && (
        <div className="log-popup-overlay" onClick={() => setSelectedLog(null)}>
          <div className="log-popup" onClick={e => e.stopPropagation()}>
            <div className="log-popup-header">
              <span className="log-popup-title">
                {selectedLog.type === 'start' && '🟢 開始'}
                {selectedLog.type === 'node_enter' && '⏩ 実行中'}
                {selectedLog.type === 'node_complete' && '✅ 完了'}
                {selectedLog.type === 'edge_active' && '→ 転送'}
                {selectedLog.type === 'edge_skipped' && '⊘ スキップ'}
                {selectedLog.type === 'done' && '🏁 終了'}
                {selectedLog.type === 'error' && '❌ エラー'}
                {selectedLog.node && ` — ${selectedLog.node}`}
              </span>
              <button className="btn btn-secondary btn-sm" onClick={() => setSelectedLog(null)}>✕</button>
            </div>
            <div className="log-popup-body">
              <table className="log-popup-table">
                <tbody>
                  <tr><td className="log-popup-label">タイプ</td><td>{selectedLog.type}</td></tr>
                  {selectedLog.node && <tr><td className="log-popup-label">ノード</td><td>{selectedLog.node}</td></tr>}
                  {selectedLog.source && <tr><td className="log-popup-label">ソース</td><td>{selectedLog.source}</td></tr>}
                  {selectedLog.target && <tr><td className="log-popup-label">ターゲット</td><td>{selectedLog.target}</td></tr>}
                  {selectedLog.condition && <tr><td className="log-popup-label">条件</td><td>{selectedLog.condition}</td></tr>}
                  <tr><td className="log-popup-label">タイムスタンプ</td><td>{new Date(selectedLog.timestamp).toLocaleTimeString()}</td></tr>
                </tbody>
              </table>
              {selectedLog.input && (
                <div className="log-popup-section">
                  <div className="log-popup-section-title">📥 入力</div>
                  <pre className="log-popup-pre">{selectedLog.input}</pre>
                </div>
              )}
              {selectedLog.output && (
                <div className="log-popup-section">
                  <div className="log-popup-section-title">📤 出力</div>
                  <pre className="log-popup-pre">{selectedLog.output}</pre>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


// ── Animated Workflow Graph ──────────────────────────────────────────

function AnimatedWorkflowGraph({
  definition,
  activeNodes,
  activeEdges,
  nodeOutputs,
}: {
  definition: WorkflowDefinition
  activeNodes: Record<string, 'processing' | 'completed' | 'idle'>
  activeEdges: Record<string, 'flowing' | 'done' | 'idle'>
  nodeOutputs: Record<string, string>
}) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([])

  const { flowNodes, flowEdges } = useMemo(() => {
    if (!definition?.executors) return { flowNodes: [], flowEdges: [] }

    const executors = definition.executors
    const edgeDefs = definition.edges || []

    // Auto-layout: BFS for levels
    const adj: Record<string, string[]> = {}
    executors.forEach(e => { adj[e.name] = [] })
    edgeDefs.forEach(e => {
      if (adj[e.source]) adj[e.source].push(e.target)
    })

    const levels: Record<string, number> = {}
    const queue = [definition.start]
    levels[definition.start] = 0
    while (queue.length) {
      const node = queue.shift()!
      for (const child of (adj[node] || [])) {
        if (levels[child] === undefined) {
          levels[child] = (levels[node] || 0) + 1
          queue.push(child)
        }
      }
    }

    const byLevel: Record<number, string[]> = {}
    Object.entries(levels).forEach(([name, level]) => {
      if (!byLevel[level]) byLevel[level] = []
      byLevel[level].push(name)
    })

    executors.forEach(e => {
      if (levels[e.name] === undefined) {
        const maxLevel = Math.max(0, ...Object.values(levels))
        levels[e.name] = maxLevel + 1
        if (!byLevel[levels[e.name]]) byLevel[levels[e.name]] = []
        byLevel[levels[e.name]].push(e.name)
      }
    })

    const computedNodes: Node[] = executors.map(e => {
      const level = levels[e.name] ?? 0
      const siblings = byLevel[level] || [e.name]
      const idx = siblings.indexOf(e.name)
      const totalWidth = siblings.length * 220
      const offsetX = idx * 220 - totalWidth / 2 + 110

      const nodeState = activeNodes[e.name] || 'idle'
      const output = nodeOutputs[e.name] || ''

      return {
        id: e.name,
        position: { x: 300 + offsetX, y: level * 150 + 40 },
        data: {
          label: (
            <PlaygroundNodeContent
              name={e.name}
              type={e.type}
              isStart={e.name === definition.start}
              state={nodeState}
              output={output}
            />
          ),
        },
        sourcePosition: Position.Bottom,
        targetPosition: Position.Top,
        style: { background: 'transparent', border: 'none', padding: 0 },
      }
    })

    const computedEdges: FlowEdge[] = edgeDefs.map((e, i) => {
      const edgeKey = `${e.source}->${e.target}`
      const edgeState = activeEdges[edgeKey] || 'idle'

      let strokeColor = '#4b5563'
      let strokeWidth = 1.5
      let animated = false

      if (edgeState === 'flowing') {
        strokeColor = '#f59e0b'
        strokeWidth = 3
        animated = true
      } else if (edgeState === 'done') {
        strokeColor = '#22c55e'
        strokeWidth = 2
      } else if (e.condition) {
        strokeColor = '#6366f1'
        animated = true
      }

      return {
        id: `e-${i}`,
        source: e.source,
        target: e.target,
        label: e.condition || '',
        labelStyle: { fill: '#9ca3af', fontSize: 11 },
        style: { stroke: strokeColor, strokeWidth },
        markerEnd: { type: MarkerType.ArrowClosed, color: strokeColor },
        animated,
      }
    })

    return { flowNodes: computedNodes, flowEdges: computedEdges }
  }, [definition, activeNodes, activeEdges, nodeOutputs])

  useEffect(() => {
    setNodes(flowNodes)
    setEdges(flowEdges)
  }, [flowNodes, flowEdges, setNodes, setEdges])

  if (!nodes.length) {
    return <div className="empty-state"><p>グラフデータがありません</p></div>
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      nodesDraggable={true}
      fitView
      proOptions={{ hideAttribution: true }}
      style={{ background: 'var(--bg-panel-body)' }}
    >
      <Background color="var(--border)" gap={20} />
      <Controls />
    </ReactFlow>
  )
}


function PlaygroundNodeContent({
  name,
  type,
  isStart,
  state,
  output,
}: {
  name: string
  type: string
  isStart: boolean
  state: 'processing' | 'completed' | 'idle'
  output: string
}) {
  const stateClass = state !== 'idle' ? `wf-node-${state}` : ''

  return (
    <div
      className={`workflow-node ${type} ${stateClass}`}
      style={isStart && state === 'idle' ? { boxShadow: '0 0 12px rgba(99,102,241,0.4)' } : {}}
    >
      <div className="workflow-node-label">
        {state === 'processing' && <span className="wf-node-pulse" />}
        {state === 'completed' && '✅ '}
        {name}
      </div>
      <div className="workflow-node-type">
        {type === 'agent' ? '🤖 Agent' : '⚙️ Function'}
        {isStart && ' (start)'}
      </div>
      {output && state === 'completed' && (
        <div className="wf-node-output" title={output}>
          {output.length > 60 ? output.slice(0, 60) + '...' : output}
        </div>
      )}
    </div>
  )
}
