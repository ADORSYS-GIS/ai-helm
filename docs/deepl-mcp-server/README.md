# DeepL MCP Server Investigation

This repository compares two DeepL MCP server implementations:

- [deepl-mcp-server](/home/franck-sorel/mcp/deepl-mcp-server): the official DeepL implementation
- [deepl-mcp-server-from-watchdeater-pavel](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel): an independent implementation by `watchdealer-pavel`

The goal of this document is to explain:

- what each server implements
- how the MCP request flow works
- which capabilities are available in each codebase
- where each server is strong or weak
- whether either server is production-ready for Kubernetes
- which implementation should be selected as the base for a production system

This README was built from local code inspection plus current MCP and DeepL references gathered with Tavily and Context7.

## Executive Summary

If the decision is "which implementation should we adopt as the base," the answer is:

- Choose the official [deepl-mcp-server](/home/franck-sorel/mcp/deepl-mcp-server) if feature coverage matters most.
- Choose the Pavel implementation only if you want a smaller, cleaner TypeScript starting point and you do not need document translation or glossary support yet.

For a real production deployment, neither server is ready as-is.

The main reason is architectural, not cosmetic:

- both servers are MCP `stdio` subprocesses
- neither is implemented as a remote MCP server using Streamable HTTP
- neither includes production-grade health checks, metrics, tests, or deployment hardening

That means both are good local MCP servers or agent-side subprocesses, but not yet good shared remote services for Kubernetes.

## The Two Implementations

### 1. Official DeepL Server

Path:

- [deepl-mcp-server](/home/franck-sorel/mcp/deepl-mcp-server)

Main entrypoint:

- [src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs)

Technical characteristics:

- JavaScript ESM
- uses `@modelcontextprotocol/sdk` high-level `McpServer`
- uses the official `deepl-node` client library
- exposes more tools than the alternative implementation
- includes a basic Dockerfile and Smithery config

### 2. Pavel Server

Path:

- [deepl-mcp-server-from-watchdeater-pavel](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel)

Main entrypoint:

- [src/index.ts](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel/src/index.ts)

Technical characteristics:

- TypeScript
- uses lower-level MCP request handlers
- calls DeepL over raw HTTP with `axios`
- exposes fewer tools
- has better basic operational hygiene in the code

## MCP Architecture Context

According to the MCP specification, `stdio` transport means the client launches the server as a subprocess and communicates with it over `stdin` and `stdout`. That is exactly how both implementations work.

This is visible in both codebases:

- official server startup: [deepl-mcp-server/src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs#L441)
- Pavel server startup: [deepl-mcp-server-from-watchdeater-pavel/src/index.ts](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel/src/index.ts#L395)

The important implication:

- `stdio` is a strong fit for local tools, desktop clients, and per-session agent subprocesses
- `stdio` is not the natural fit for a shared multi-client Kubernetes service

Current MCP guidance also supports remote servers using Streamable HTTP, which is the better transport for a remote deployment because it supports HTTP POST/GET, multiple client connections, optional SSE streaming, and session management.

## How The Flow Works

### High-Level Request Flow

For both servers, the flow is:

1. An MCP client starts the process.
2. The process connects a `StdioServerTransport`.
3. The client lists tools.
4. The client calls a tool with arguments.
5. The server validates input.
6. The server calls DeepL.
7. The server returns MCP `content` back to the client.

### Official Server Flow

The official server uses the higher-level `McpServer` API. Tools are registered declaratively with `server.tool(...)`.

Relevant code:

- server creation: [deepl-mcp-server/src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs#L110)
- tool registration: [deepl-mcp-server/src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs#L120)

Example:

```js
server.tool(
  "translate-text",
  "Translate text to a target language using DeepL API...",
  {
    text: z.string().describe("Text to translate"),
    sourceLangCode: z.string().optional(),
    targetLangCode: z.string().describe("target language code"),
    formality: z.enum(formalityTypes).optional(),
    glossaryId: z.string().optional(),
  },
  translateText
);
```

This style is concise and maps well to MCP tool concepts.

### Pavel Server Flow

The Pavel server uses lower-level MCP primitives. It defines a `TOOLS` array, registers `ListTools` and `CallTool` handlers, then dispatches with a `switch`.

Relevant code:

- tool definitions: [deepl-mcp-server-from-watchdeater-pavel/src/index.ts](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel/src/index.ts#L70)
- manual dispatch: [deepl-mcp-server-from-watchdeater-pavel/src/index.ts](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel/src/index.ts#L211)

Example:

```ts
switch (name) {
  case 'translate_text':
    return await this.translateText(args);
  case 'get_usage':
    return await this.getUsage();
  default:
    throw new McpError(ErrorCode.MethodNotFound, `Tool '${name}' not found.`);
}
```

This gives more explicit control over request handling, but it is more verbose and easier to drift from SDK conventions if the codebase grows.

## Capability Comparison

### Official DeepL Server Capabilities

Implemented tools:

- `get-source-languages`
- `get-target-languages`
- `translate-text`
- `get-writing-styles`
- `get-writing-tones`
- `rephrase-text`
- `translate-document`
- `list-glossaries`
- `get-glossary-info`
- `get-glossary-dictionary-entries`

Where they are registered:

- [deepl-mcp-server/src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs#L120)

What this means in practice:

- text translation is supported
- rephrasing is supported
- document translation is supported
- glossary discovery and glossary entry retrieval are supported
- writing style and tone discovery are supported

This is the more complete implementation.

### Pavel Server Capabilities

Implemented tools:

- `translate_text`
- `rephrase_text`
- `get_source_languages`
- `get_target_languages`
- `get_usage`

Where they are defined:

- [deepl-mcp-server-from-watchdeater-pavel/src/index.ts](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel/src/index.ts#L70)

What this means in practice:

- text translation is supported
- rephrasing is supported
- source/target language discovery is supported
- API quota visibility is supported

What is missing compared with the official server:

- no document translation
- no glossary APIs
- no writing style or tone discovery

## DeepL Feature Mapping

This section maps the local code to DeepL platform capabilities.

### Text Translation

DeepL supports text translation, automatic source language detection, formality, context, glossary usage, and batching.

The official server exposes many of these:

- `sourceLangCode`
- `targetLangCode`
- `formality`
- `glossaryId`
- `context`
- `preserveFormatting`
- `splitSentences`
- `customInstructions`

Code:

- [deepl-mcp-server/src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs#L132)

The Pavel server exposes a smaller but still useful subset:

- `text`
- `target_lang`
- `source_lang`
- `formality`
- `context`
- `preserve_formatting`
- `glossary_id`
- `split_sentences`

Code:

- [deepl-mcp-server-from-watchdeater-pavel/src/index.ts](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel/src/index.ts#L25)

One important difference:

- the official server only accepts a single string for `translate-text`
- Pavel's server accepts either a string or an array and converts both into a DeepL batch request

Code:

- [deepl-mcp-server-from-watchdeater-pavel/src/index.ts](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel/src/index.ts#L26)

This is a real strength in Pavel's design.

### Rephrasing

Both servers implement rephrasing using DeepL Write.

Official server:

- [deepl-mcp-server/src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs#L276)

Pavel server:

- [deepl-mcp-server-from-watchdeater-pavel/src/index.ts](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel/src/index.ts#L270)

The official server is stronger here because it exposes writing `style` and `tone` explicitly and separately.

The Pavel server is stronger operationally because it handles the common "not on this DeepL plan" `403` case cleanly and returns a controlled MCP error response.

### Document Translation

Only the official server implements document translation:

- [deepl-mcp-server/src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs#L303)

This matters for real enterprise use cases such as:

- translating PDFs or DOCX files
- localization workflows for deliverables
- back-office translation pipelines

The Pavel server cannot currently serve those workflows.

### Glossaries

Only the official server implements glossary discovery and glossary entry retrieval:

- list glossaries: [deepl-mcp-server/src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs#L343)
- glossary info: [deepl-mcp-server/src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs#L364)
- dictionary entries: [deepl-mcp-server/src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs#L381)

This is a major differentiator for production translation systems because glossaries are usually essential for:

- company terminology
- brand consistency
- product naming
- legal or regulated domain language

### Usage and Quota

Only the Pavel server exposes usage:

- [deepl-mcp-server-from-watchdeater-pavel/src/index.ts](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel/src/index.ts#L329)

This is operationally useful because it helps:

- show current quota consumption
- support cost control
- reduce surprise outages from exhausted quota

This capability should exist in the final selected implementation.

## Strengths And Weaknesses

### Official DeepL Server

#### Strengths

- widest feature coverage
- uses the official DeepL Node SDK instead of hand-built HTTP calls
- includes document translation
- includes glossary metadata and dictionary retrieval
- includes writing style and tone discovery
- uses the higher-level `McpServer` API, which is simpler to maintain for tool registration
- includes Dockerfile and Smithery configuration

Why those strengths matter:

- official SDK usage reduces API drift risk
- glossary and document support move it closer to enterprise translation requirements
- broader tool coverage gives the agent more autonomy and better self-service workflows

#### Weaknesses

- no explicit startup validation for `DEEPL_API_KEY`
- performs network-dependent language loading during process startup
- no graceful shutdown handling
- minimal packaging and no real test suite
- no usage/quota tool
- no explicit retries, metrics, or structured logging
- written in plain JS rather than strict TS

Why those weaknesses matter:

- startup can fail before the server is available
- operations teams get little visibility
- it is harder to trust behavior under load or during API failures
- production hardening work is still required

#### Example Weakness In Code

The official server eagerly calls DeepL to fetch languages at module load time:

- [deepl-mcp-server/src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs#L103)

That means server startup depends on external API availability before the process is even ready to serve MCP calls.

### Pavel Server

#### Strengths

- cleaner TypeScript codebase
- explicit env var validation at startup
- API free/pro endpoint auto-detection
- manual but clear error handling
- timeout configured on HTTP client
- graceful shutdown on `SIGINT` and `SIGTERM`
- includes usage/quota reporting
- supports batch text translation input

Why those strengths matter:

- easier to maintain and harden operationally
- fewer hidden assumptions during startup
- better visibility into API failures and quotas
- better suited for controlled backend engineering work

#### Weaknesses

- much narrower feature set
- no document translation
- no glossary tools
- no style/tone enumeration tools
- relies on raw `axios` calls instead of the official DeepL SDK
- no Dockerfile
- no test suite

Why those weaknesses matter:

- it does not cover many real translation platform use cases
- raw HTTP integration increases the chance of drift as DeepL evolves
- feature gaps would need to be closed before it could replace the official implementation

#### Example Strength In Code

The Pavel server validates `DEEPL_API_KEY` immediately:

- [deepl-mcp-server-from-watchdeater-pavel/src/index.ts](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel/src/index.ts#L14)

It also handles signal-based shutdown:

- [deepl-mcp-server-from-watchdeater-pavel/src/index.ts](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel/src/index.ts#L191)

That is basic but correct production-oriented engineering.

## Use Cases

### Best Use Cases For The Official DeepL Server

- local Claude/Desktop style DeepL assistant integration
- terminology-heavy translation with glossary support
- document translation workflows
- translation assistants for localization or support teams
- enterprise translation use cases where feature breadth matters

Why:

- it exposes the richer DeepL feature surface
- it aligns more closely with what DeepL offers as a platform

### Best Use Cases For The Pavel Server

- a simple local translation MCP tool
- a smaller codebase for experimentation
- a base for a custom internal server if only text translation is needed initially
- internal proof of concept where usage/quota reporting is important

Why:

- it is easier to follow
- it has better immediate operational hygiene
- the smaller scope reduces complexity if advanced features are not required

## Is Either Server Production Ready For Kubernetes?

Short answer:

- no, not as a shared remote MCP service

### Why Not

Both servers use `StdioServerTransport` only.

This means:

- the MCP client must start the server process directly
- the server is not listening on an HTTP endpoint
- the server is not designed for many remote clients
- the server has no HTTP session management, no health endpoints, and no remote auth layer

For Kubernetes, the expected production shape is usually:

- remote MCP over Streamable HTTP
- one or more HTTP endpoints
- readiness and liveness probes
- centralized logs and metrics
- authentication and authorization
- request limits and rate limiting

Neither repository currently implements that.

### What Containerization Would Mean Today

Containerizing the current official server is possible because there is already a Dockerfile:

- [deepl-mcp-server/Dockerfile](/home/franck-sorel/mcp/deepl-mcp-server/Dockerfile)

But that does not make it production-ready by itself.

A containerized `stdio` MCP server is still mostly useful in these patterns:

- sidecar per agent session
- ephemeral job container
- local workstation integration packaged in a container

It is not yet a good general remote MCP platform service.

## Recommended Improvements

### Improvements Required For Either Server

- add Streamable HTTP transport for remote deployment
- add readiness and liveness endpoints
- add structured logging
- add metrics and tracing
- add automated tests
- add retry and backoff policy for transient DeepL failures
- add request size and file size limits
- add rate limiting if exposed as a shared service
- add secret management guidance for Kubernetes

### Improvements Specifically For The Official Server

- validate `DEEPL_API_KEY` explicitly at startup
- remove eager startup dependency on language fetches
- add graceful shutdown
- add `get-usage`
- migrate to TypeScript or strengthen type safety
- add integration tests around glossary, rephrase, and document translation

### Improvements Specifically For The Pavel Server

- switch DeepL access from raw `axios` to the official `deepl-node` SDK where possible
- add document translation support
- add glossary support
- add writing style and tone listing
- add Docker packaging

## Which One Should Be Implemented?

### Recommendation

Use the official [deepl-mcp-server](/home/franck-sorel/mcp/deepl-mcp-server) as the implementation base.

### Why

- it already covers the important DeepL platform capabilities
- it uses the official DeepL Node SDK
- it supports document translation and glossaries, which are the biggest missing enterprise features in the Pavel implementation
- it is closer to a feature-complete DeepL MCP server

### But Do Not Ship It Unchanged

The best practical path is:

1. start from the official server
2. port in the best operational ideas from Pavel's implementation
3. add remote MCP transport for Kubernetes if remote service deployment is required

### The Hybrid Target State

The ideal implementation would combine:

- official server feature breadth
- Pavel server operational hygiene
- remote Streamable HTTP transport
- tests, health checks, observability, and deployment hardening

That combined design would be the correct production candidate.

## Concrete Final Decision Matrix

### Pick The Official Server If You Need

- glossary support
- document translation
- broader DeepL feature coverage
- lower risk of API drift through the official SDK

### Pick Pavel's Server If You Need

- a simpler TypeScript base
- quota visibility from day one
- a smaller codebase for experimentation
- only text translation and rephrasing in the first phase

### Final Recommendation

If there will be only one implementation moving forward, choose the official server and harden it.

That is the better long-term engineering decision.

## Reference Snippets

### Official Server: Translation Call Through DeepL SDK

Source:

- [deepl-mcp-server/src/index.mjs](/home/franck-sorel/mcp/deepl-mcp-server/src/index.mjs#L251)

```js
const result = await deeplClient.translateText(text, sourceLangCode, targetLangCode, options);
const translation = result;

return mcpContentifyText([
  translation.text,
  `Detected source language: ${translation.detectedSourceLang}`,
  `Target language used: ${targetLangCode}`
]);
```

This is the strongest implementation choice in the repository because it uses the official DeepL client abstraction instead of manually constructing HTTP calls.

### Pavel Server: Usage Reporting

Source:

- [deepl-mcp-server-from-watchdeater-pavel/src/index.ts](/home/franck-sorel/mcp/deepl-mcp-server-from-watchdeater-pavel/src/index.ts#L329)

```ts
const response = await this.axiosInstance.get<DeepLUsage>('/v2/usage');

const result = {
  character_count: usage.character_count,
  character_limit: usage.character_limit,
  characters_remaining: usage.character_limit - usage.character_count,
  percent_used: `${percentUsed}%`,
  api_type: IS_FREE_API ? 'Free' : 'Pro',
};
```

This is a capability worth carrying into the chosen implementation.

## External References

Primary references used for this investigation:

- MCP transports: https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
- MCP TypeScript SDK examples: https://github.com/modelcontextprotocol/typescript-sdk/blob/main/docs/server.md
- DeepL text translation API: https://developers.deepl.com/api-reference/translate
- DeepL getting started and production guidance: https://developers.deepl.com/docs/getting-started/intro
- DeepL Node client reference: https://github.com/deeplcom/deepl-node/blob/main/README.md

## Final Conclusion

The official DeepL MCP server is the better implementation to keep, but it is not yet a production-ready Kubernetes service.

Pavel's implementation is the better example of baseline engineering hygiene, but it is too narrow in capability to be the final answer unless the product scope is intentionally small.

The right decision is:

- implement the official server as the base
- borrow Pavel's operational ideas
- add remote transport and production hardening before calling it production-ready
