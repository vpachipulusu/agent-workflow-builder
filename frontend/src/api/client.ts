const API_BASE = '/api';

export interface AgentDefinition {
  name: string;
  description: string;
  instructions: string;
  model: string;
  tools: { name: string; description: string }[];
  temperature: number;
}

export interface AgentCreateResponse {
  name: string;
  definition: AgentDefinition;
  code: string;
  validation: { valid: boolean; errors: string[] };
  message: string;
}

export interface ExecutorDef {
  name: string;
  type: 'agent' | 'function';
  instructions: string;
  model: string;
}

export interface EdgeDef {
  source: string;
  target: string;
  condition: string | null;
  fan_in: boolean;
}

export interface WorkflowDefinition {
  name: string;
  description: string;
  start: string;
  executors: ExecutorDef[];
  edges: EdgeDef[];
}

export interface WorkflowCreateResponse {
  name: string;
  definition: WorkflowDefinition;
  code: string;
  validation: { valid: boolean; errors: string[] };
  message: string;
}

// ── Agents ────────────────────────────────────────────────────────────────

export async function createAgentFromPrompt(prompt: string): Promise<AgentCreateResponse> {
  const res = await fetch(`${API_BASE}/agents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createAgentFromDefinition(definition: AgentDefinition): Promise<AgentCreateResponse> {
  const res = await fetch(`${API_BASE}/agents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ definition }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listAgents(): Promise<{ agents: { name: string; description: string; model: string; source_workflow?: string | null }[] }> {
  const res = await fetch(`${API_BASE}/agents`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAgent(name: string): Promise<{ name: string; definition: Record<string, unknown>; code: string }> {
  const res = await fetch(`${API_BASE}/agents/${name}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteAgent(name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/agents/${name}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await res.text());
}

export async function editAgent(agentName: string, prompt: string): Promise<AgentCreateResponse> {
  const res = await fetch(`${API_BASE}/agents/${agentName}/edit`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_name: agentName, prompt }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Workflows ─────────────────────────────────────────────────────────────

export async function createWorkflowFromPrompt(prompt: string): Promise<WorkflowCreateResponse> {
  const res = await fetch(`${API_BASE}/workflows`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createWorkflowFromDefinition(definition: WorkflowDefinition): Promise<WorkflowCreateResponse> {
  const res = await fetch(`${API_BASE}/workflows`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ definition }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function editWorkflow(workflowName: string, prompt: string): Promise<WorkflowCreateResponse> {
  const res = await fetch(`${API_BASE}/workflows/${workflowName}/edit`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workflow_name: workflowName, prompt }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listWorkflows(): Promise<{
  workflows: { name: string; description: string; executors_count: number; edges_count: number }[];
}> {
  const res = await fetch(`${API_BASE}/workflows`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getWorkflow(name: string): Promise<{ name: string; definition: Record<string, unknown>; code: string }> {
  const res = await fetch(`${API_BASE}/workflows/${name}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteWorkflow(name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/workflows/${name}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await res.text());
}

// ── Playground – Agent ─────────────────────────────────────────────────

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export async function runAgent(
  name: string,
  message: string,
  history: ChatMessage[],
  onToken: (content: string) => void,
  onDone: (fullContent: string) => void,
  onError: (error: string) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/agents/${name}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  });
  if (!res.ok) {
    onError(await res.text());
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const data = JSON.parse(line.slice(6));
        if (data.type === 'token') onToken(data.content);
        else if (data.type === 'done') onDone(data.content);
        else if (data.type === 'error') onError(data.content);
      } catch { /* skip malformed */ }
    }
  }
}

// ── Playground – Workflow ──────────────────────────────────────────────

export interface WorkflowEvent {
  type: 'start' | 'node_enter' | 'node_complete' | 'edge_active' | 'edge_skipped' | 'done' | 'error';
  condition?: string;
  matched?: boolean;
  workflow?: string;
  input?: string;
  step?: number;
  node?: string;
  output?: string;
  source?: string;
  target?: string;
  data_preview?: string;
  steps?: number;
  content?: string;
}

export async function runWorkflow(
  name: string,
  message: string,
  onEvent: (event: WorkflowEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/workflows/${name}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) {
    onEvent({ type: 'error', content: await res.text() });
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const data = JSON.parse(line.slice(6));
        onEvent(data as WorkflowEvent);
      } catch { /* skip malformed */ }
    }
  }
}
