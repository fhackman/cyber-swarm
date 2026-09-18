# CYBER SWARM TRADING OS --- Design Specification

## 1. Purpose

CYBER SWARM is an AI-native autonomous trading command center inspired
by the provided GrokTopus visual language.

The design goal is not to create a dashboard that merely looks like AI.
It must expose the actual decision pipeline:

`Market Data → Specialized Agents → Consensus → Risk Gate → Execution → Fill → Portfolio → Audit`

Primary visual language:

-   Dark graphite / near-black command center
-   Neon semantic status colors
-   Quant terminal typography
-   Live network visualization
-   Agent swarm topology
-   Dense information hierarchy without visual clutter
-   Every visual state must map to real system state

## 2. Product Principles

1.  **Truth over decoration** --- no fake metrics, fake AI activity, or
    simulated P&L in production.
2.  **Risk before execution** --- consensus never bypasses the risk
    engine.
3.  **Explainability** --- every order must have an auditable decision
    chain.
4.  **Fail closed** --- missing/stale market data, model failure, broker
    failure, or risk uncertainty defaults to HOLD.
5.  **Human observability** --- operators can inspect agents, signals,
    orders, risk, and system health.
6.  **Provider agnostic** --- models and data providers are replaceable
    behind interfaces.
7.  **Event driven** --- important state changes are represented as
    immutable events.

## 3. Information Architecture

### Global Header

-   Product identity
-   Market status
-   System mode: LIVE / PAPER / BACKTEST / SAFE
-   Swarm cycle
-   Uptime
-   Connectivity
-   Emergency stop

### Market Ticker

Supported initial instruments:

-   XAUUSD
-   BTCUSD
-   EURUSD
-   USOIL

Additional symbols must be configuration-driven.

### KPI Row

-   Net Equity
-   Realized P&L
-   Unrealized P&L
-   24h Volume
-   Win Rate
-   Drawdown
-   Open Positions
-   Risk Exposure

### Main Workspace

Left/right auxiliary panels:

-   Balance history
-   Activity/event log
-   Market regime
-   Risk cockpit

Center:

-   Swarm Core
-   Agent topology
-   Signal flow
-   Consensus state

Bottom:

-   Agent cards
-   Consensus bar
-   Orders
-   Positions
-   System health

## 4. Agent Model

Initial logical agents:

  Agent   Responsibility
  ------- --------------------------------------------
  NORO    Pricing / valuation / market condition
  LUMEN   Sentiment / news / macro interpretation
  TIDAL   Technical and market-structure scanner
  ZEPHR   Liquidity / spread / market microstructure
  RUNE    Risk management
  OKAPI   Hedging / correlation
  VESKA   Execution quality / order routing
  MARIN   Portfolio / settlement / reconciliation

Agents must communicate through typed contracts rather than unrestricted
text.

Example:

``` yaml
Signal:
  symbol: XAUUSD
  direction: SELL
  confidence: 0.82
  timeframe: M15
  evidence:
    - liquidity_sweep
    - bearish_structure
  timestamp: ISO-8601
  model_version: v1.0.0
```

## 5. Consensus Engine

Consensus is weighted aggregation, not simple majority voting.

Conceptual formula:

`Consensus = Σ(weight × confidence × reliability) / Σ(weight)`

Recommended states:

-   `<55%` HOLD
-   `55–70%` WATCH
-   `70–80%` SIGNAL
-   `80–90%` HIGH CONFIDENCE
-   `>90%` EXTREME CONSENSUS

Thresholds are configuration, not hard-coded constants.

Consensus must include:

-   participating agents
-   agent weights
-   confidence
-   reliability
-   evidence references
-   timestamp
-   market regime
-   model versions

## 6. Risk Gate

No order reaches MT5 directly from an AI agent.

Required pipeline:

`Signal → Consensus → Risk Gate → Liquidity Check → Spread Check → Session Check → Exposure Check → Position Sizing → Execution`

Risk gate checks:

-   maximum risk per trade
-   daily loss limit
-   maximum drawdown
-   maximum total exposure
-   symbol exposure
-   correlated exposure
-   maximum open positions
-   spread
-   slippage
-   trading session
-   news/event lock
-   stale data
-   broker connection
-   emergency stop

Failure result: `REJECT` or `HOLD`.

## 7. Visual Design Tokens

### Background

-   BG-0: #070A0E
-   BG-1: #0D1117
-   BG-2: #131922
-   BORDER: #26303A

### Text

-   PRIMARY: #E8EDF2
-   SECONDARY: #78838E
-   MUTED: #4E5964

### Semantic Colors

-   Green: profit / healthy / approved
-   Red: loss / rejected / critical
-   Orange: pricing / active processing
-   Yellow: sentiment / warning
-   Cyan: scanner / data / execution
-   Blue: infrastructure / neutral

Neon colors are semantic, not decorative.

## 8. Typography

Primary:

-   Inter

Technical:

-   JetBrains Mono

Display accents:

-   Rajdhani or Orbitron

Use monospace for:

-   prices
-   P&L
-   latency
-   IDs
-   timestamps
-   event logs

## 9. Core Components

``` text
MetricCard
MarketTicker
AgentCard
AgentDetailPanel
SwarmCore
AgentNetwork
SignalCard
ConsensusBar
RiskCockpit
ActivityLog
MarketChart
PositionTable
OrderTable
SystemHealth
EmergencyStop
StatusBadge
LatencyIndicator
ModelStatus
```

Every component must support:

-   loading
-   healthy
-   warning
-   degraded
-   offline
-   error
-   empty

## 10. Swarm Visualization

The center visualization represents actual system topology.

Node size:

`importance × activity`

Edge intensity:

`message frequency / signal relevance`

Particle direction:

-   BUY: agent → core → execution
-   SELL: reverse semantic flow
-   Risk rejection: flow terminates at Risk Gate
-   Error: edge becomes inactive

Avoid animation that communicates fake activity.

## 11. AI Decision Timeline

Every trade should expose a timeline such as:

``` text
03:07:12.021  TIDAL detected liquidity sweep
03:07:12.083  NORO bearish 78%
03:07:12.109  LUMEN neutral 52%
03:07:12.121  ZEPHR sell-side liquidity confirmed
03:07:12.144  RUNE risk approved
03:07:12.168  Consensus SELL 81%
03:07:12.184  VESKA submitted order
03:07:12.231  MARIN confirmed fill
```

This is an audit feature, not merely UI decoration.

## 12. Responsive Strategy

Desktop-first because trading requires high information density.

Breakpoints:

-   Large desktop: full command center
-   Laptop: collapse secondary panels
-   Tablet: tabbed panels
-   Mobile: monitoring only by default; execution requires explicit
    confirmation and strong authentication

## 13. Accessibility

-   Do not rely on color alone.
-   Use labels/icons for BUY, SELL, HOLD, REJECT.
-   Maintain readable contrast.
-   Respect reduced-motion preferences.
-   Critical alerts must be persistent, not animation-only.

## 14. Security UI

Display:

-   API/broker connection state without exposing secrets
-   model identity/version
-   execution mode
-   permission state
-   last heartbeat
-   emergency stop state

Never display:

-   API keys
-   access tokens
-   broker passwords
-   private credentials

## 15. Design Acceptance Criteria

A production screen is accepted only if:

-   every displayed metric has a real data source;
-   every agent state comes from the backend;
-   every order can be traced to a decision chain;
-   no UI action can bypass risk controls;
-   LIVE/PAPER/BACKTEST modes are visually unmistakable;
-   stale data is visibly indicated;
-   system failure defaults to a safe state.
