"""Quick test for Agent and Workflow creation APIs."""

import json
import sys
import httpx

BASE = "http://localhost:8000/api"


def test_health():
    r = httpx.get(f"{BASE}/health", timeout=10)
    assert r.status_code == 200
    print("✓ Health check OK")


def test_create_agent_nl():
    print("\n=== Test: Agent creation (NL) ===")
    r = httpx.post(
        f"{BASE}/agents",
        json={"prompt": "顧客からの問い合わせを分類し適切な回答を生成するカスタマーサポートエージェント"},
        timeout=60,
    )
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"✓ Agent created: {data['name']}")
        print(f"  Description: {data['definition']['description']}")
        print(f"  Validation: {'✓ PASS' if data['validation']['valid'] else '✗ FAIL'}")
        if not data["validation"]["valid"]:
            for e in data["validation"]["errors"]:
                print(f"    Error: {e}")
        return data["name"]
    else:
        print(f"✗ Failed: {r.text[:500]}")
        return None


def test_create_agent_manual():
    print("\n=== Test: Agent creation (Manual) ===")
    r = httpx.post(
        f"{BASE}/agents",
        json={
            "definition": {
                "name": "code_reviewer",
                "description": "コードレビューを行うエージェント",
                "instructions": "あなたはシニアソフトウェアエンジニアです。ユーザーから提出されたコードをレビューし、改善点を具体的に指摘してください。セキュリティ、パフォーマンス、可読性の観点からレビューを行い、改善案をコード例とともに提示してください。",
                "model": "gpt-4.1",
                "tools": [],
                "temperature": 0.3,
            }
        },
        timeout=30,
    )
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"✓ Agent created: {data['name']}")
        print(f"  Validation: {'✓ PASS' if data['validation']['valid'] else '✗ FAIL'}")
        if not data["validation"]["valid"]:
            for e in data["validation"]["errors"]:
                print(f"    Error: {e}")
        return data["name"]
    else:
        print(f"✗ Failed: {r.text[:500]}")
        return None


def test_list_agents():
    print("\n=== Test: List agents ===")
    r = httpx.get(f"{BASE}/agents", timeout=30)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"✓ Agents: {len(data['agents'])}")
        for a in data["agents"]:
            print(f"  - {a['name']}: {a['description']}")
    else:
        print(f"✗ Failed: {r.text[:200]}")


def test_create_workflow_nl():
    print("\n=== Test: Workflow creation (NL) ===")
    r = httpx.post(
        f"{BASE}/workflows",
        json={
            "prompt": "メールを受信し、スパム判定エージェントで分類する。正常なメールには自動返信エージェントが返信を作成し、スパムメールはログに記録して破棄するワークフロー"
        },
        timeout=60,
    )
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"✓ Workflow created: {data['name']}")
        print(f"  Description: {data['definition']['description']}")
        print(f"  Executors: {len(data['definition']['executors'])}")
        print(f"  Edges: {len(data['definition']['edges'])}")
        print(f"  Validation: {'✓ PASS' if data['validation']['valid'] else '✗ FAIL'}")
        if not data["validation"]["valid"]:
            for e in data["validation"]["errors"]:
                print(f"    Error: {e}")
        return data["name"]
    else:
        print(f"✗ Failed: {r.text[:500]}")
        return None


def test_edit_workflow():
    # First create a workflow to edit
    r_create = httpx.post(
        f"{BASE}/workflows",
        json={"prompt": "メールを受信し、スパム判定を行い、正常なメールには自動返信するワークフロー"},
        timeout=60,
    )
    assert r_create.status_code == 200, f"Failed to create workflow for edit test: {r_create.text[:200]}"
    name = r_create.json()["name"]

    print(f"\n=== Test: Workflow edit (NL) for '{name}' ===")
    r = httpx.put(
        f"{BASE}/workflows/{name}/edit",
        json={
            "workflow_name": name,
            "prompt": "スパムフィルターの後に、管理者へ通知するステップを追加してください",
        },
        timeout=60,
    )
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"✓ Workflow edited: {data['name']}")
        print(f"  Executors: {len(data['definition']['executors'])}")
        print(f"  Edges: {len(data['definition']['edges'])}")
        print(f"  Validation: {'✓ PASS' if data['validation']['valid'] else '✗ FAIL'}")
        if not data["validation"]["valid"]:
            for e in data["validation"]["errors"]:
                print(f"    Error: {e}")
    else:
        print(f"✗ Failed: {r.text[:500]}")


def test_list_workflows():
    print("\n=== Test: List workflows ===")
    r = httpx.get(f"{BASE}/workflows", timeout=30)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"✓ Workflows: {len(data['workflows'])}")
        for w in data["workflows"]:
            print(f"  - {w['name']}: {w['description']} ({w['executors_count']} execs, {w['edges_count']} edges)")
    else:
        print(f"✗ Failed: {r.text[:200]}")


def test_run_agent():
    """Test the agent playground SSE endpoint."""
    print("\n=== Test: Run agent (playground) ===")
    # Get first available agent
    r = httpx.get(f"{BASE}/agents", timeout=30)
    assert r.status_code == 200
    agents = r.json()["agents"]
    if not agents:
        print("⏭ Skipped: no agents available")
        return
    name = agents[0]["name"]
    print(f"  Running agent: {name}")
    with httpx.stream(
        "POST",
        f"{BASE}/agents/{name}/run",
        json={"message": "Hello, who are you?", "history": []},
        timeout=60,
    ) as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("data: "):
                import json
                events.append(json.loads(line[6:]))
        assert any(e["type"] == "done" for e in events), f"No 'done' event found in {events}"
        print(f"✓ Agent responded with {len(events)} SSE events")


def test_run_workflow():
    """Test the workflow playground SSE endpoint."""
    print("\n=== Test: Run workflow (playground) ===")
    r = httpx.get(f"{BASE}/workflows", timeout=30)
    assert r.status_code == 200
    workflows = r.json()["workflows"]
    if not workflows:
        print("⏭ Skipped: no workflows available")
        return
    name = workflows[0]["name"]
    print(f"  Running workflow: {name}")
    with httpx.stream(
        "POST",
        f"{BASE}/workflows/{name}/run",
        json={"message": "Test input data"},
        timeout=120,
    ) as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("data: "):
                import json
                events.append(json.loads(line[6:]))
        assert any(e["type"] == "done" for e in events), f"No 'done' event in workflow events: {[e['type'] for e in events]}"
        print(f"✓ Workflow completed with {len(events)} SSE events")
        for e in events:
            if e["type"] == "node_complete":
                print(f"  ✅ {e.get('node')}: {str(e.get('output', ''))[:80]}")


if __name__ == "__main__":
    print("=" * 60)
    print("  Agent & Workflow Builder - Integration Tests")
    print("=" * 60)

    test_health()

    # Agent tests
    agent1 = test_create_agent_nl()
    agent2 = test_create_agent_manual()
    test_list_agents()

    # Workflow tests
    wf_name = test_create_workflow_nl()
    test_edit_workflow()
    test_list_workflows()

    # Playground tests
    test_run_agent()
    test_run_workflow()

    print("\n" + "=" * 60)
    print("  Tests complete!")
    print("=" * 60)
