> Historical assessment: use release_claims_matrix.md and milestones/M9-RC.md for current scope/results.

# Prior-art audit — 2026-10-13

Documentation was accessed through web retrieval before implementation. This is a feature-documentation audit, not a locally executed competitor benchmark. Supported means documented, not independently performance-validated. Absence of documentation is unknown, not proof of absence.

Sources: [LangGraph time travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel), [LangSmith](https://docs.langchain.com/langsmith/observability), [Langfuse](https://langfuse.com/docs/observability/overview), [Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/), [tracing processor source](https://github.com/openai/openai-agents-python/blob/main/src/agents/tracing/processors.py), [OTel GenAI](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md), [Phoenix](https://arize.com/docs/phoenix/tracing/how-to-tracing), [Playwright](https://playwright.dev/docs/trace-viewer), [Temporal replay testing](https://docs.temporal.io/develop/python/best-practices/testing-suite).

Legend: S = supported and verified in documentation; P = partially supported; U = unknown or insufficient evidence. No unsupported verdict is inferred from silence.

| Capability | LangGraph | LangSmith | Langfuse | Agents SDK | OTel | Phoenix | Playwright | Temporal |
|---|---|---|---|---|---|---|---|---|
| Event tracing | P | S | S | S | S | S | S | S |
| Structured tool recording | P | S | S | S | S | S | P | P |
| State checkpoints | S | U | U | U | U | U | P | P |
| Recorded inspection | S | S | S | P | P | S | S | S |
| Deterministic execution replay | P | U | U | U | U | U | U | S |
| Checkpoint fork | S | U | U | U | U | U | U | P |
| Tool-result editing | P | U | U | U | U | U | U | U |
| Intervention re-execution | S | U | U | U | U | U | U | U |
| Side-effect inspection | P | P | P | P | P | P | S | P |
| Branch comparison | P | P | P | U | U | U | U | U |
| Tamper-evident storage | U | U | U | U | U | U | U | U |
| Local-first | S | P | P | P | S | S | S | P |
| Offline core | S | U | P | P | S | S | S | P |
| Evidence export | P | P | P | P | P | P | S | S |

LangGraph already resumes after modified checkpoints. Its documentation explicitly says downstream nodes, including model calls and APIs, execute again and may return different results. GhostFrame cannot claim to invent checkpoint branching. Agents SDK already has tracing processors; Playwright already has a mature trace inspector. Temporal supplies a much broader durable execution and replay system.

Additional direct overlap discovered: [agentrr](https://github.com/ip174/agentrr) advertises offline replay of boundary calls and divergence; [agentreplay](https://github.com/gadda00/agentreplay) advertises replay/counterfactual debugging; [Agent-Devtools](https://github.com/Jacopos311/Agent-Devtools) advertises local inspection, diff, and replay. agentrr and agentreplay public pages were retrieved. Agent-Devtools was visible in search results but its direct page retrieval failed, so its detailed capabilities remain unknown. Implementation fidelity is not independently established here. Treat overlapping claims as prior art, not as verified product guarantees.

## Decision
Proceed as a bounded engineering implementation: an inspectable scripted-runtime reference, with checkpoint restoration, schema-validated observation replacement, independent virtual-state accounting and integrity evidence. No first-ever, research-novelty, hidden-reasoning, universal replay, universal prompt-injection defense, or production sandbox claim. Originality lies in implementation choices and evidence quality; commercial differentiation remains unproven.
