import { useState } from 'react'

import {
  ApiError,
  editDefinition,
  messageOf,
  resetDefinition,
  saveDefinition,
  type Definition,
  type DefinitionView,
} from '../../api/weekendSaver'
import { stepKind } from './graphLayout'

const EXAMPLES = [
  'Add an AI step that summarizes the results in two sentences before the report',
  'Before planning, stop a disable run if more than ten resources are listed',
  'Add an AI step that explains the plan in plain words before approval',
  'Do not ask for approval on manual runs',
]

interface Problem {
  message: string
  errors: string[]
}

interface Props {
  view: DefinitionView
  onChanged: (view: DefinitionView) => void
}

export default function CustomizePanel({ view, onChanged }: Props) {
  const [prompt, setPrompt] = useState('')
  const [working, setWorking] = useState(false)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [json, setJson] = useState<string | null>(null)

  const attempt = async (change: () => Promise<DefinitionView>): Promise<boolean> => {
    setWorking(true)
    setProblem(null)
    try {
      onChanged(await change())
      // The text in the JSON editor describes the workflow as it was before this change
      setJson(null)
      return true
    } catch (error) {
      const errors = error instanceof ApiError ? error.errors : []
      setProblem({ message: messageOf(error), errors })
      return false
    } finally {
      setWorking(false)
    }
  }

  const applyPrompt = async () => {
    if (await attempt(() => editDefinition(prompt.trim()))) setPrompt('')
  }

  const saveJson = async () => {
    let parsed: Definition
    try {
      parsed = JSON.parse(json ?? '')
    } catch {
      setProblem({ message: 'That is not valid JSON, so nothing was saved.', errors: [] })
      return
    }
    await attempt(() => saveDefinition(parsed))
  }

  const reset = async () => {
    if (!window.confirm('Remove every added step and setting and go back to the default workflow?')) {
      return
    }
    await attempt(resetDefinition)
  }

  const custom = view.definition.executors.filter(step => step.type !== 'builtin')
  // A chat edit can change a setting too, so every departure from the defaults is listed
  const changedSettings = view.definition.executors.flatMap(step => {
    const defaults = view.catalog.find(item => item.name === step.name)?.settings ?? []
    return Object.entries(step.config ?? {})
      .filter(([name, value]) => defaults.find(item => item.name === name)?.default !== value)
      .map(([name, value]) => ({ step: step.name, name, value }))
  })

  return (
    <div className="card ws-card">
      <div className="card-header">
        <span className="card-title">Customize</span>
        <span className={`badge ${view.is_default ? 'badge-success' : 'badge-workflow'}`}>
          {view.is_default ? 'Default workflow' : 'Customized'}
        </span>
      </div>

      <p className="ws-hint">
        Describe a change. The six built-in steps stay; you can add AI notes, AI gates that stop
        a disable run before anything changes, and adjust step settings. A change that breaks a
        rule is not saved.
      </p>

      <textarea
        className="form-textarea chat-textarea"
        aria-label="Describe a change to the workflow"
        placeholder="e.g. Add an AI step that summarizes the results before the report"
        value={prompt}
        disabled={working}
        onChange={event => setPrompt(event.target.value)}
      />
      <div className="ws-examples">
        {EXAMPLES.map(example => (
          <button
            key={example}
            type="button"
            className="ws-chip"
            disabled={working}
            onClick={() => setPrompt(example)}
          >
            {example}
          </button>
        ))}
      </div>
      <div className="ws-actions">
        <button
          className="btn btn-primary btn-sm"
          disabled={working || !prompt.trim()}
          onClick={applyPrompt}
        >
          {working ? 'Working…' : 'Apply change'}
        </button>
        <button
          className="btn btn-secondary btn-sm"
          disabled={working}
          onClick={() =>
            setJson(json === null ? JSON.stringify(view.definition, null, 2) : null)
          }
        >
          {json === null ? 'Edit as JSON' : 'Close JSON'}
        </button>
        <button
          className="btn btn-danger btn-sm"
          disabled={working || view.is_default}
          onClick={reset}
        >
          Reset to default
        </button>
      </div>

      {problem && (
        <div className="ws-problem" role="alert">
          <strong>{problem.message}</strong>
          {problem.errors.length > 0 && (
            <ul>
              {problem.errors.map((error, index) => (
                <li key={`${index}-${error}`}>{error}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {view.errors.length > 0 && (
        <div className="ws-problem" role="alert">
          <strong>The saved workflow cannot run as it is.</strong> Enable runs use the default
          workflow until this is fixed; disable runs do not start.
          <ul>
            {view.errors.map((error, index) => (
              <li key={`${index}-${error}`}>{error}</li>
            ))}
          </ul>
        </div>
      )}

      {json !== null && (
        <div className="ws-json">
          <textarea
            className="form-textarea ws-json-text"
            aria-label="Workflow definition as JSON"
            spellCheck={false}
            value={json}
            disabled={working}
            onChange={event => setJson(event.target.value)}
          />
          <button className="btn btn-primary btn-sm" disabled={working} onClick={saveJson}>
            Save JSON
          </button>
        </div>
      )}

      {changedSettings.length > 0 && (
        <ul className="ws-steps" aria-label="Settings changed from their defaults">
          {changedSettings.map(setting => (
            <li key={`${setting.step}.${setting.name}`}>
              <span className="ws-step-name">{setting.step}</span>
              <span className="ws-step-kind">setting</span>
              <span className="ws-step-text">
                {setting.name} = {String(setting.value)}
                {setting.name === 'require_approval' && setting.value === false
                  ? ' (manual runs change resources without asking first)'
                  : ''}
              </span>
            </li>
          ))}
        </ul>
      )}

      {custom.length > 0 && (
        <ul className="ws-steps">
          {custom.map(step => (
            <li key={step.name}>
              <span className="ws-step-name">{step.name}</span>
              <span className="ws-step-kind">{stepKind(step, view.definition)}</span>
              {step.instructions && <span className="ws-step-text">{step.instructions}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
