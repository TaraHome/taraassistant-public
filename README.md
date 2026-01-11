# Tara Assistant

Most smart homes are programmable toasters in trench coats. You poke them, you script them, you pray the indentation gods hear you. Tara attempts something different. It watches how you live, finds the patterns you forgot to articulate, and turns those into Home Assistant automations you can actually inspect, edit, and own.

Tara does not guess. It observes. When behavior becomes structure, Tara drafts an automation, hands it to you in YAML, and waits for your blessing. No charts. No voice syntax manuals. No devops cosplay. You just live and the house takes notes.

## Why this exists

Home automation today splits into two tribes. The first tribe wants total control through YAML, scenes, triggers, and the ritual sacrifice of evenings. The second tribe wants magic. Neither tribe is wrong. The problem is that magic breaks without visibility, and control becomes labor without learning.

Tara is an attempt to merge the two. It learns without ceremony and generates automations without hiding the wiring. You get autonomy with auditability. The house becomes helpful without becoming unpredictable.

## How it works

Tara runs locally and talks to Home Assistant through its API. It collects state changes, user inputs, and other events. It stores these locally, models your routines, and surfaces patterns once they are consistent enough to matter.

When a pattern holds, Tara drafts an automation in plain Home Assistant YAML and waits for approval. If you accept it, Tara hands the finished automation to Home Assistant. If you reject it, Tara records that feedback and drops the idea. Nothing updates behind your back.

Simple intent commands like `turn on the living room lights` or `lock the front door` bypass the learning side and execute directly through Home Assistant services. More complex requests that need reasoning can route through an LLM provider of your choice. Sensitive actions are guarded by a safety layer that asks for confirmation before anything irreversible happens.

You can think of it as a local assistant that tries to write the boring automations you were going to create anyway, but only after you see the diff.



## Installation

Pull the container:

```bash
docker pull ghcr.io/tarahome/taraassistant:latest
```

Run it:

```bash
docker run -d   --name tara-assistant   --restart unless-stopped   -p 8000:8000   -v $(pwd)/data:/app/data   ghcr.io/tarahome/taraassistant:latest
```

Open your browser at:

```text
http://localhost:8000
```

Connect to your Home Assistant instance, configure a provider if you want one, and start watching what Tara suggests.




## Architecture

Tara is built as a local service that sits between your habits and Home Assistant. It is intentionally simple from the outside and opinionated on the inside.

### High level view

```text
Your Browser
  Chat UI / Setup / Logs

          |
          v

Tara FastAPI Server (local)
  Intent Classifier
  Guardrails and Safety
  Fast Path Executor
  Event Collector
  Pattern Detector
  Automation Generator

          |
          v

LLM Provider (optional)
  OpenAI / Anthropic / Google / Ollama / OpenAI-compatible 

          |
          v

Home Assistant API
  Devices, Services, States, Automations
```

### FastAPI Runtime

The server exposes a local HTTP API and a browser UI. This is where you connect Home Assistant, configure providers, and review what Tara is doing. All processing runs locally except the optional calls to LLMs you explicitly enable.

### Event Collector

This component listens to Home Assistant events and service calls. It records things like:

- state changes  
- service calls and scenes  
- user initiated actions from the UI or voice  
- timestamps and basic context  

Data is stored locally under the data volume. No external telemetry, no silent uploads.

### Pattern Detector

This is where the learning happens. The detector scans the event history for routines that look intentional rather than random. Examples include:

- a light that always turns on around sunset in the same room when you arrive  
- media starting and lights dimming in the same window of time  
- doors locking on a consistent nighttime schedule  

The detector is conservative. It waits for consistency and avoids racing to conclusions. The goal is to surface things you clearly do on purpose, not noise from experiments or guests.

### Intent Agent

The intent agent handles natural language commands. For trivial intents that map directly to Home Assistant services it skips any heavy lifting and executes them immediately.

For higher level instructions it can call an LLM provider, translate the instruction into Home Assistant service calls or prospective automations, and then pass those through the same safety and approval path as learned patterns.

### Guardrails and Safety

The safety layer classifies actions into categories such as harmless, reversible, or sensitive. Sensitive actions include things like:

- locking and unlocking doors  
- modifying security scenes  
- changing critical climate settings  

For those, Tara does not silently execute. It prompts for confirmation, and, when appropriate, presents the underlying YAML or service call so you know exactly what is about to happen.

### Automation Generator

When a pattern is stable enough, or when you request a new rule, this component renders an actual Home Assistant automation in YAML. It tries to generate readable, editable automations that follow common Home Assistant conventions rather than clever tricks.

The generator produces:

- triggers based on the events and conditions that were observed  
- conditions that capture context, such as time windows or modes  
- actions that reflect what actually happened in the house  

You review the proposed automation, see the YAML, and choose whether to enable it. Tara never edits your Home Assistant configuration without your explicit decision.

### Home Assistant Integration

Tara uses the Home Assistant API for all interactions. It does not bypass or replace your existing automations. It lives alongside them. You can:

- accept generated automations and then edit them directly in Home Assistant  
- ignore or delete suggestions you do not like  
- keep your existing manual automations unchanged  

Home Assistant remains the source of truth. Tara is a suggestion and orchestration layer, not a new control plane.

## Deployment model

Self hosted. Local storage. Encrypted credentials. No external accounts. No telemetry. Cloud connectivity is opt in and only for whichever LLM provider you configure.

Your Home Assistant remains in charge. Tara is an add on brain, not a landlord.


## What Tara is not

- Tara is not a cloud lock in scheme.  
- It is not a replacement for Home Assistant.  
- It is not a guarantee that you never touch YAML again.  

It is a local service that tries to learn from your actual behavior and turn that into automations you can see, edit, version, and delete. No miracles, just pattern detection and your approval.

## Status and expectations

This project is early. There will be rough edges. The learning logic is intentionally cautious. Pattern scoring is opinionated. The UI exists so you can inspect behavior instead of guessing.

Planned areas of growth include:

- stronger recognition of household modes like guests, sleeping, and vacation  
- better conflict handling between generated automations and existing ones  
- clearer explanations for why a suggestion appeared  

If you prefer your smart home quiet and predictable, Tara aims to stay on that side of the line.


Automation is mostly about modeling habits without annoying people. Better primitives and more transparent behavior win.
