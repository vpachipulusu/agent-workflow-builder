# Agent Definition Schema

## Required Fields

| Field          | Type   | Constraints                   |
|----------------|--------|-------------------------------|
| `name`         | string | snake_case, max 64 chars      |
| `description`  | string | max 256 chars                 |
| `instructions` | string | 10–32,000 chars               |
| `model`        | string | valid deployment name          |

## Optional Fields

| Field              | Type   | Default |
|--------------------|--------|---------|
| `tools`            | list   | `[]`    |
| `context_providers`| list   | `[]`    |
| `temperature`      | float  | `0.7`   |

## Example

```yaml
name: travel_planner
description: Plans travel itineraries based on user preferences
model: gpt-4o
instructions: |
  You are a travel planning assistant.
  Help users plan trips by:
  - Suggesting destinations
  - Creating day-by-day itineraries
  - Recommending hotels and restaurants
  - Providing budget estimates
  
  Always ask for: destination preferences, dates, budget, and interests.
tools: []
temperature: 0.7
```
