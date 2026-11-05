# Workflow Patterns Reference

## Pattern 1: Linear Pipeline

```
A → B → C
```

```yaml
executors:
  - name: step_a
    type: function
  - name: step_b
    type: function
  - name: step_c
    type: function
edges:
  - source: step_a
    target: step_b
  - source: step_b
    target: step_c
start: step_a
```

```python
builder = WorkflowBuilder(start_executor=step_a)
builder.add_edge(step_a, step_b)
builder.add_edge(step_b, step_c)
workflow = builder.build()
```

## Pattern 2: Conditional Branching

```
Classifier → (if billing) → BillingAgent
           → (if tech)    → TechAgent
```

```yaml
executors:
  - name: classifier
    type: agent
    instructions: "Classify input into categories"
  - name: billing_agent
    type: agent
  - name: tech_agent
    type: agent
edges:
  - source: classifier
    target: billing_agent
    condition: "category == 'billing'"
  - source: classifier
    target: tech_agent
    condition: "category == 'technical'"
start: classifier
```

## Pattern 3: Fan-out / Fan-in

```
Splitter → Worker1 ─┐
         → Worker2 ──┤→ Aggregator
         → Worker3 ─┘
```

```yaml
executors:
  - name: splitter
    type: function
  - name: worker1
    type: agent
  - name: worker2
    type: agent
  - name: worker3
    type: agent
  - name: aggregator
    type: function
edges:
  - source: splitter
    target: worker1
  - source: splitter
    target: worker2
  - source: splitter
    target: worker3
  - source: worker1
    target: aggregator
    fan_in: true
  - source: worker2
    target: aggregator
    fan_in: true
  - source: worker3
    target: aggregator
    fan_in: true
start: splitter
```

## Pattern 4: Loop / Iteration

```
Processor → Checker → (if not done) → Processor
                    → (if done)     → Output
```

```yaml
executors:
  - name: processor
    type: agent
  - name: checker
    type: function
  - name: output
    type: function
edges:
  - source: processor
    target: checker
  - source: checker
    target: processor
    condition: "not is_complete"
  - source: checker
    target: output
    condition: "is_complete"
start: processor
```

## Edge Type Quick Reference

| Type       | Python API                                                                |
|------------|---------------------------------------------------------------------------|
| Direct     | `builder.add_edge(source, target)`                                        |
| Conditional| `builder.add_edge(source, target, condition=lambda data: ...)`            |
| Switch-Case| `builder.add_switch_case_edge_group(source, [Case(...), Default(...)])`   |
| Fan-out    | `builder.add_fan_out_edges(source, [target1, target2])`                   |
| Fan-in     | `builder.add_fan_in_edges([s1, s2, s3], target)`                          |
| Chain      | `builder.add_chain([step1, step2, step3])`                                |

## Agent vs AgentExecutor

- `Agent`: Standalone agent instance. Created in agents tab.
- `AgentExecutor`: Wraps an Agent for use inside a Workflow.
- `WorkflowBuilder` auto-wraps Agent → AgentExecutor when passed directly.

```python
# Agent-type executors are imported from agents tab:
from classifier.agent import create_agent as create_classifier
classifier = await create_classifier()

# Pass Agent directly to builder (auto-wrapped in AgentExecutor)
builder = WorkflowBuilder(start_executor=classifier)
builder.add_edge(classifier, billing_agent)
```
