import { useState, useEffect, useRef, useCallback } from 'react'
import {
  createAgentFromPrompt,
  createAgentFromDefinition,
  editAgent,
  listAgents,
  getAgent,
  deleteAgent,
  runAgent,
  type AgentCreateResponse,
  type AgentDefinition,
  type ChatMessage,
} from '../api/client'

type TabMode = 'chat' | 'manual'

interface BuilderMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  agentResult?: AgentCreateResponse | null
}

export default function AgentBuilderPage() {
  const [tab, setTab] = useState<TabMode>('chat')
  const [agents, setAgents] = useState<{ name: string; description: string; model: string; source_workflow?: string | null }[]>([])
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AgentCreateResponse | null>(null)
  const [selectedAgent, setSelectedAgent] = useState<{ name: string; definition: Record<string, unknown>; code: string } | null>(null)

  // ── Builder chat state ──
  const [builderMessages, setBuilderMessages] = useState<BuilderMessage[]>([])
  const [builderInput, setBuilderInput] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const builderEndRef = useRef<HTMLDivElement>(null)

  // Manual mode
  const [manualForm, setManualForm] = useState<AgentDefinition>({
    name: '',
    description: '',
    instructions: '',
    model: 'gpt-4o',
    tools: [],
    temperature: 0.7,
  })

  // ── Playground state ──
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamBuffer, setStreamBuffer] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

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

  // ── Result view tab ──
  const [resultView, setResultView] = useState<'yaml' | 'code'>('yaml')

  const refreshList = () => {
    listAgents().then(d => setAgents(d.agents)).catch(() => {})
  }

  useEffect(() => { refreshList() }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamBuffer])

  useEffect(() => {
    builderEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [builderMessages, loading])

  // ── New creation ──
  const handleNew = () => {
    setIsCreating(true)
    setBuilderMessages([{
      role: 'system',
      content: '新しいエージェントを作成します。どんなエージェントを作りたいですか？説明してください。',
    }])
    setResult(null)
    setSelectedAgent(null)
    setMessages([])
    setStreamBuffer('')
    setBuilderInput('')
  }

  // ── Builder chat send ──
  const handleBuilderSend = async () => {
    if (!builderInput.trim() || loading) return
    const userMsg: BuilderMessage = { role: 'user', content: builderInput.trim() }
    setBuilderMessages(prev => [...prev, userMsg])
    setBuilderInput('')
    setLoading(true)

    const currentName = result?.name || selectedAgent?.name

    try {
      let res: AgentCreateResponse
      if (!currentName) {
        res = await createAgentFromPrompt(userMsg.content)
      } else {
        res = await editAgent(currentName, userMsg.content)
      }

      setResult(res)
      if (res.name) {
        const data = await getAgent(res.name)
        setSelectedAgent(data)
        setMessages([])
        setStreamBuffer('')
      }
      refreshList()

      const action = currentName ? '更新' : '作成'
      const assistantMsg: BuilderMessage = {
        role: 'assistant',
        content: res.validation.valid
          ? `✅ エージェント「${res.name}」を${action}しました。\n\n引き続きチャットで修正できます。例：\n• 「もっと丁寧な口調にして」\n• 「ツールを追加して」\n• 「Temperature を 0.3 にして」`
          : `⚠️ エージェント「${res.name}」を${action}しましたが、バリデーションエラーがあります：\n${res.validation.errors.join('\n')}`,
        agentResult: res,
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

  // ── Edit selected agent via chat ──
  const handleEditSelectedAgent = () => {
    if (!selectedAgent) return
    setIsCreating(true)
    setBuilderMessages([{
      role: 'system',
      content: `エージェント「${selectedAgent.name}」を編集モードで開きました。どのように変更しますか？`,
    }])
    setBuilderInput('')
  }

  const handleManualCreate = async () => {
    if (!manualForm.name || !manualForm.instructions) return
    setLoading(true)
    setResult(null)
    try {
      const res = await createAgentFromDefinition(manualForm)
      setResult(res)
      if (res.name) {
        const data = await getAgent(res.name)
        setSelectedAgent(data)
        setMessages([])
        setStreamBuffer('')
      }
      refreshList()
    } catch (e: any) {
      setResult({ name: '', definition: {} as any, code: '', validation: { valid: false, errors: [e.message] }, message: e.message })
    } finally {
      setLoading(false)
    }
  }

  const handleSelectAgent = async (name: string) => {
    try {
      const data = await getAgent(name)
      setSelectedAgent(data)
      setResult(null)
      setIsCreating(false)
      setBuilderMessages([])
      setMessages([])
      setStreamBuffer('')
    } catch {}
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`エージェント "${name}" を削除しますか？`)) return
    await deleteAgent(name)
    setSelectedAgent(null)
    setResult(null)
    setIsCreating(false)
    setBuilderMessages([])
    setMessages([])
    refreshList()
  }

  // ── Playground chat ──
  const currentAgentName = result?.name || selectedAgent?.name || ''
  const currentInstructions = (() => {
    if (selectedAgent?.definition) {
      return (selectedAgent.definition as Record<string, unknown>).instructions as string || ''
    }
    return ''
  })()

  const handleSend = async () => {
    if (!chatInput.trim() || !currentAgentName || streaming) return
    const userMsg: ChatMessage = { role: 'user', content: chatInput.trim() }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setChatInput('')
    setStreaming(true)
    setStreamBuffer('')
    let fullResponse = ''
    await runAgent(
      currentAgentName,
      userMsg.content,
      newMessages,
      (token) => { fullResponse += token; setStreamBuffer(fullResponse) },
      (content) => { setMessages(prev => [...prev, { role: 'assistant', content }]); setStreamBuffer(''); setStreaming(false) },
      (error) => { setMessages(prev => [...prev, { role: 'assistant', content: `エラー: ${error}` }]); setStreamBuffer(''); setStreaming(false) },
    )
  }

  const activeName = result?.name || selectedAgent?.name || ''

  // Sub-component for center panel tab buttons
  const ResultTabButtons = () => (
    <div className="devui-tabs tabs" style={{ borderBottom: 'none', marginBottom: 0 }}>
      <button className={`tab ${resultView === 'yaml' ? 'active' : ''}`} onClick={() => setResultView('yaml')}>
        YAML
      </button>
      <button className={`tab ${resultView === 'code' ? 'active' : ''}`} onClick={() => setResultView('code')}>
        Python
      </button>
    </div>
  )

  // ── Determine center panel display mode ──
  const showBuilderChat = tab === 'chat' && isCreating
  const hasAgent = !!(result || selectedAgent)
  const showEmpty = tab === 'chat' && !isCreating && !hasAgent

  return (
    <div className="devui-shell">
      {/* ── Top Toolbar ── */}
      <div className="devui-toolbar">
        <div className="devui-toolbar-title">🤖 エージェント</div>
        <div className="devui-tabs tabs" style={{ borderBottom: 'none', marginBottom: 0, flexShrink: 0 }}>
          <button className={`tab ${tab === 'chat' ? 'active' : ''}`} onClick={() => setTab('chat')}>
            💬 自然言語
          </button>
          <button className={`tab ${tab === 'manual' ? 'active' : ''}`} onClick={() => setTab('manual')}>
            ✏️ 手動
          </button>
        </div>
        <div style={{ flex: 1 }} />
        {tab === 'chat' && (
          <div className="devui-toolbar-actions">
            <button className="btn btn-primary btn-sm" onClick={handleNew}>
              ＋ 新規作成
            </button>
          </div>
        )}
      </div>

      {/* ── Three-column body ── */}
      <div className="devui-body">
        {/* Left: Agent list */}
        <div className="devui-list-panel">
          <div className="devui-list-header">
            <span className="devui-list-header-title">エージェント</span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{agents.length}</span>
          </div>
          <div className="devui-list-body">
            {agents.length === 0 ? (
              <div className="devui-empty">
                <div className="devui-empty-icon">🤖</div>
                <span>まだなし</span>
              </div>
            ) : (
              agents.map(a => (
                <div
                  key={a.name}
                  className={`devui-list-item ${selectedAgent?.name === a.name ? 'devui-list-item--active' : ''}`}
                  onClick={() => handleSelectAgent(a.name)}
                >
                  <div className="devui-list-item-name">
                    {a.name}
                    {a.source_workflow && (
                      <span className="badge badge-workflow" title={`ワークフロー「${a.source_workflow}」から自動生成`}>WF</span>
                    )}
                  </div>
                  <div className="devui-list-item-desc">{a.description}</div>
                  <div className="devui-list-item-meta">
                    {a.model}
                    {a.source_workflow && <span style={{ marginLeft: 6, opacity: 0.7 }}>← {a.source_workflow}</span>}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Center: Builder Chat + Code view / Manual form */}
        <div className="devui-center" ref={centerRef}>
          {tab === 'manual' && (
            <div style={{ overflow: 'auto', flex: 1, padding: 20 }}>
              <div style={{ maxWidth: 600 }}>
                <div className="form-group">
                  <label className="form-label">名前 (snake_case)</label>
                  <input className="form-input" placeholder="customer_support_agent" value={manualForm.name}
                    onChange={e => setManualForm({ ...manualForm, name: e.target.value })} />
                </div>
                <div className="form-group">
                  <label className="form-label">説明</label>
                  <input className="form-input" placeholder="顧客サポート用のAIエージェント" value={manualForm.description}
                    onChange={e => setManualForm({ ...manualForm, description: e.target.value })} />
                </div>
                <div className="form-group">
                  <label className="form-label">インストラクション (システムプロンプト)</label>
                  <textarea className="form-textarea" style={{ minHeight: 180 }} placeholder="あなたはカスタマーサポートの専門家です。..."
                    value={manualForm.instructions}
                    onChange={e => setManualForm({ ...manualForm, instructions: e.target.value })} />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <div className="form-group">
                    <label className="form-label">モデル</label>
                    <select className="form-select" value={manualForm.model}
                      onChange={e => setManualForm({ ...manualForm, model: e.target.value })}>
                      <option value="gpt-4o">gpt-4o</option>
                      <option value="gpt-4o-mini">gpt-4o-mini</option>
                      <option value="gpt-4.1">gpt-4.1</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Temperature</label>
                    <input className="form-input" type="number" min={0} max={2} step={0.1} value={manualForm.temperature}
                      onChange={e => setManualForm({ ...manualForm, temperature: parseFloat(e.target.value) })} />
                  </div>
                </div>
                <button className="btn btn-primary" onClick={handleManualCreate} disabled={loading || !manualForm.name || !manualForm.instructions}>
                  {loading ? <span className="spinner" /> : 'エージェント作成'}
                </button>
              </div>
            </div>
          )}

          {/* Builder Chat (creation / edit mode) — resizable top panel */}
          {showBuilderChat && (
            <div className="builder-chat-panel" style={{ flex: `0 0 ${chatPanelPct}%`, maxHeight: `${chatPanelPct}%`, minHeight: 0, borderBottom: '2px solid rgba(99,102,241,0.3)' }}>
              <div className="builder-chat-header">
                <span className="builder-chat-header-title">💬 エージェント作成チャット</span>
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
                    placeholder={result?.name ? '修正内容を入力... (例: 「もっと丁寧な口調にして」)' : 'エージェントの説明を入力...'}
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
          {showBuilderChat && (
            <div className="resize-handle-h" onMouseDown={handleDragStart} />
          )}

          {/* Empty state */}
          {showEmpty && (
            <div className="devui-empty">
              <div className="devui-empty-icon">🤖</div>
              <span>エージェントを作成または選択してください</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                「＋ 新規作成」ボタンか、左のリストからエージェントを選んでください
              </span>
            </div>
          )}

          {/* Placeholder below chat when no agent exists yet */}
          {showBuilderChat && !hasAgent && (
            <div className="devui-center-full" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>チャットでエージェントの説明を入力してください</span>
            </div>
          )}

          {/* Code/YAML detail — shown below builder chat or full when not creating */}
          {hasAgent && result && (
            <div className="devui-center-full">
              <div className="devui-center-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>作成結果: {result.name}</span>
                  <span className={`badge ${result.validation.valid ? 'badge-success' : 'badge-error'}`}>
                    {result.validation.valid ? '✓ OK' : '✗ Error'}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  <ResultTabButtons />
                  {!isCreating && (
                    <button className="btn btn-accent btn-sm" onClick={handleEditSelectedAgent}>
                      ✏️ チャットで編集
                    </button>
                  )}
                </div>
              </div>
              {!result.validation.valid && (
                <div style={{ padding: '8px 16px', background: 'var(--error-glow)', borderBottom: '1px solid var(--border)' }}>
                  {result.validation.errors.map((e, i) => (
                    <p key={i} style={{ color: 'var(--error)', fontSize: 12 }}>• {e}</p>
                  ))}
                </div>
              )}
              <div className="devui-center-body">
                {resultView === 'yaml' ? (
                  <pre className="code-block">{typeof result.definition === 'string' ? result.definition : JSON.stringify(result.definition, null, 2)}</pre>
                ) : (
                  <pre className="code-block">{result.code}</pre>
                )}
              </div>
            </div>
          )}

          {hasAgent && selectedAgent && !result && (
            <div className="devui-center-full">
              <div className="devui-center-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>{selectedAgent.name}</span>
                </div>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  <ResultTabButtons />
                  {!isCreating && (
                    <button className="btn btn-accent btn-sm" onClick={handleEditSelectedAgent}>
                      ✏️ チャットで編集
                    </button>
                  )}
                  <button className="btn btn-danger btn-sm" onClick={() => handleDelete(selectedAgent.name)}>🗑️</button>
                </div>
              </div>
              <div className="devui-center-body">
                {resultView === 'yaml' ? (
                  <pre className="code-block">{typeof selectedAgent.definition === 'string' ? selectedAgent.definition : JSON.stringify(selectedAgent.definition, null, 2)}</pre>
                ) : (
                  <pre className="code-block">{selectedAgent.code}</pre>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Right: Chat Playground */}
        <div className="devui-right">
          <div className="devui-right-header">
            <span className="devui-right-header-title">
              🎮 {activeName ? activeName : 'プレイグラウンド'}
            </span>
            {activeName && messages.length > 0 && (
              <button className="btn btn-secondary btn-sm" onClick={() => { setMessages([]); setStreamBuffer('') }}>
                🗑️
              </button>
            )}
          </div>

          {activeName ? (
            <>
              {/* System prompt preview */}
              {currentInstructions && messages.length === 0 && !streaming && (
                <div style={{ padding: '0 12px', marginTop: 8, flexShrink: 0 }}>
                  <div className="devui-system-prompt">
                    <div className="devui-system-prompt-label">System Prompt</div>
                    {currentInstructions.length > 200 ? currentInstructions.slice(0, 200) + '...' : currentInstructions}
                  </div>
                </div>
              )}

              {/* Messages */}
              <div className="devui-messages">
                {messages.length === 0 && !streaming && (
                  <div className="devui-empty">
                    <span style={{ fontSize: 12 }}>メッセージを送信してテスト</span>
                  </div>
                )}
                {messages.map((msg, i) => (
                  <div key={i} className={`playground-msg playground-msg-${msg.role}`}>
                    <div className="playground-msg-role">
                      {msg.role === 'user' ? '👤 You' : `🤖 ${activeName}`}
                    </div>
                    <div className="playground-msg-content">{msg.content}</div>
                  </div>
                ))}
                {streaming && streamBuffer && (
                  <div className="playground-msg playground-msg-assistant">
                    <div className="playground-msg-role">🤖 {activeName}</div>
                    <div className="playground-msg-content">
                      {streamBuffer}
                      <span className="playground-cursor" />
                    </div>
                  </div>
                )}
                {streaming && !streamBuffer && (
                  <div className="playground-msg playground-msg-assistant">
                    <div className="playground-msg-role">🤖 {activeName}</div>
                    <div className="playground-msg-content">
                      <span className="playground-thinking">考え中...</span>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Input */}
              <div className="devui-right-footer">
                <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
                  <textarea
                    className="form-input chat-textarea"
                    placeholder="メッセージを入力..."
                    value={chatInput}
                    onChange={e => setChatInput(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                        e.preventDefault()
                        handleSend()
                      }
                    }}
                    disabled={streaming}
                    rows={2}
                    style={{ flex: 1, padding: '8px 12px', fontSize: 13 }}
                  />
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={handleSend}
                    disabled={streaming || !chatInput.trim()}
                    style={{ alignSelf: 'flex-end', marginBottom: 2 }}
                  >
                    {streaming ? <span className="spinner" /> : '送信'}
                  </button>
                </div>
                <div className="chat-textarea-hint">Ctrl+Enter で送信</div>
              </div>
            </>
          ) : (
            <div className="devui-empty">
              <div className="devui-empty-icon">💬</div>
              <span>エージェントを選択してチャット</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// End of AgentBuilderPage
