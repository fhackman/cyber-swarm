# CYBER SWARM TRADING OS --- Project Context

## 1. Project Identity

Name:

**CYBER SWARM TRADING OS**

Concept:

An AI-native autonomous trading operating system inspired by a
multi-agent swarm command center.

The reference visual shows a dark cyberpunk dashboard with a central
swarm organism, specialized agents around it, market metrics, activity
logs, and a consensus indicator.

The implementation must preserve the visual concept while turning it
into a real, auditable trading system.

## 2. Core Mental Model

``` text
OBSERVE
  ↓
UNDERSTAND
  ↓
DEBATE
  ↓
CONSENSUS
  ↓
RISK CHECK
  ↓
EXECUTE
  ↓
VERIFY
  ↓
LEARN
```

The dashboard is the visible surface of this pipeline.

## 3. Non-Negotiable Principles

### Data Integrity

Never invent:

-   price
-   P&L
-   volume
-   market condition
-   news
-   signal
-   performance

If data is unavailable, report `NO DATA`.

### Trading Safety

AI agents do not have unrestricted execution authority.

All execution passes through:

`Consensus → Risk Gate → Execution Service → MT5`

### Auditability

Every decision must be traceable.

Required identifiers:

``` text
event_id
signal_id
consensus_id
risk_id
order_id
broker_ticket
```

### Fail Closed

When uncertain:

`HOLD`

When a critical dependency is unavailable:

`SAFE MODE`

## 4. Initial Instruments

Primary:

-   XAUUSD
-   BTCUSD
-   EURUSD
-   USOIL

Architecture must support adding symbols through configuration rather
than code changes.

## 5. Initial Agents

  Agent   Role
  ------- -------------------------------
  NORO    Pricing
  LUMEN   Sentiment
  TIDAL   Scanner / technical structure
  ZEPHR   Liquidity
  RUNE    Risk
  OKAPI   Hedging
  VESKA   Execution
  MARIN   Portfolio / settlement

These are logical roles. They may be implemented by deterministic code,
ML models, LLMs, or combinations.

## 6. Agent Contract

Every agent should expose:

``` text
identity
version
status
input schema
output schema
confidence
reliability
evidence
latency
timestamp
```

No agent should output an unstructured paragraph as its primary
machine-to-machine interface.

## 7. Decision Contract

A signal should contain:

``` yaml
symbol:
direction:
timeframe:
confidence:
evidence:
market_regime:
model_version:
agent:
timestamp:
```

A consensus decision should contain:

``` yaml
symbol:
direction:
score:
agents_for:
agents_against:
agent_contributions:
risk_precheck:
timestamp:
```

A risk decision should contain:

``` yaml
approved:
reason:
risk_per_trade:
position_size:
stop_loss:
take_profit:
exposure:
risk_limits:
timestamp:
```

## 8. Operating Modes

The system must clearly separate:

### BACKTEST

Historical replay only.

### PAPER

Real-time decision pipeline with simulated execution.

### LIVE

Real broker execution with strict risk controls.

### SAFE

No new orders.

UI must make the current mode unmistakable.

## 9. UI Philosophy

The reference image should be treated as a design inspiration, not as a
source of fake operational data.

Use:

-   dark graphite
-   neon semantic accents
-   monospace quantitative data
-   agent cards
-   central swarm graph
-   real-time event stream
-   risk cockpit
-   market regime
-   consensus visualization

Do not use decorative animation to imply that an agent is working when
it is not.

## 10. Critical UX States

Every agent can be:

``` text
IDLE
RUNNING
SIGNAL
APPROVED
REJECTED
DEGRADED
OFFLINE
ERROR
```

System can be:

``` text
HEALTHY
WARNING
DEGRADED
SAFE
EMERGENCY_STOP
```

## 11. Risk Philosophy

The most important system rule:

**A strong AI signal is not permission to trade.**

A trade requires:

``` text
signal quality
+
consensus
+
risk approval
+
market conditions
+
execution conditions
```

## 12. Data and Model Separation

Separate responsibilities:

### Market Data

Provides facts.

### Quant Engine

Transforms facts into measurable features.

### ML

Predicts patterns/probabilities.

### LLM

Interprets context and produces structured reasoning where useful.

### Risk Engine

Determines whether risk is acceptable.

### Execution Engine

Places and manages orders.

The LLM must never be the sole source of position sizing or risk
authorization.

## 13. MT5 Role

MT5 is the broker execution bridge.

The EA should be deliberately thin and reliable.

It should:

-   receive validated instructions;
-   execute;
-   report status;
-   reconcile positions;
-   report errors;
-   maintain heartbeat.

It should not silently modify AI decisions.

## 14. Memory / Learning

Future versions may include learning from:

-   historical outcomes
-   agent accuracy
-   market regimes
-   execution quality
-   false positives
-   false negatives

Learning must not automatically change live risk parameters without
controlled validation.

Recommended lifecycle:

``` text
Observation
 → Evaluation
 → Candidate Model
 → Backtest
 → Paper
 → Approval
 → Production
```

## 15. Deployment Philosophy

Use staged deployment:

``` text
DEV
 ↓
TEST
 ↓
BACKTEST
 ↓
PAPER
 ↓
LIMITED LIVE
 ↓
FULL LIVE
```

Each stage has explicit gates.

## 16. Observability Requirements

Track:

-   market-data freshness
-   agent latency
-   agent availability
-   consensus latency
-   risk latency
-   order latency
-   fill latency
-   slippage
-   rejected orders
-   model errors
-   queue depth
-   broker connectivity
-   reconciliation status

## 17. Files Expected in the Project

``` text
designs.md
implementation_plan.md
context.md
process_log.md
AGENT.md
README.md
```

This package currently defines the first three.

## 18. Agent Operating Rule

When another coding agent continues this project:

1.  Read `context.md`.
2.  Read `designs.md`.
3.  Read `implementation_plan.md`.
4.  Inspect the current repository before changing architecture.
5.  Never assume an undocumented feature exists.
6.  Record architectural changes.
7.  Run tests after implementation.
8.  Report failures explicitly.
9.  Never claim deployment succeeded without verifying it.
10. Never fabricate market or broker data.

## 19. Current Recommended Build Order

``` text
1. Repository foundation
2. Contracts
3. Market-data adapter
4. Event bus
5. Feature engine
6. TIDAL
7. NORO
8. ZEPHR
9. Consensus
10. RUNE
11. Paper execution
12. MT5 bridge
13. Portfolio reconciliation
14. Dashboard
15. Observability
16. Failure injection
17. Additional agents
18. Controlled live deployment
```

## 20. Definition of Success

The project succeeds when the visual dashboard and actual trading engine
represent the same underlying state.

The UI must never become a separate fictional representation of the
system.

**Mental Model: the screen is the nervous system's monitor; the
risk-gated event pipeline is the actual organism.**
