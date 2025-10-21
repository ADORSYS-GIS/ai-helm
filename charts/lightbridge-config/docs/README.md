# Lightbridge Configuration Service (lightbridge-config)

## Purpose
The `lightbridge-config` Helm chart is responsible for managing the configuration of the Lightbridge authorization system. This includes defining networking and security policies, configuring connections to various AI providers, and establishing authorization policies such as rate limits, access tiers, and supported models. The chart's templates generate custom resources that are consumed by a service mesh or API gateway to enforce these policies.

## Architecture
This chart primarily defines Kubernetes Custom Resources (CRDs) that configure an underlying service mesh or API Gateway (e.g., Envoy Proxy with AI Gateway extensions). It does not deploy an application itself but rather orchestrates the configuration of other infrastructure components. It leverages `values.yaml` to define:
*   **AI Service Backends**: `AIServiceBackend` and `Backend` resources are created for each enabled AI provider, specifying their schemas and endpoints.
*   **Security Policies**: `BackendSecurityPolicy` resources are generated to handle authentication with AI providers (API keys for OpenAI, GCP credentials for Google, AWS credentials for AWS). A `SecurityPolicy` is also created for external authorization, integrating with the `lightbridge-authz` service.
*   **TLS Policies**: `BackendTLSPolicy` resources ensure secure communication with AI provider backends.
*   **Rate Limiting**: `BackendTrafficPolicy` resources are created for global rate limiting (requests and tokens per minute/month) and local burst limiting.
*   **Routing**: `AIGatewayRoute` resources map incoming requests (based on the `x-ai-eg-model` header) to the appropriate AI service backend.
*   **Client Traffic Policies**: `ClientTrafficPolicy` resources configure aspects like proxy protocol, TCP keepalive, and connection buffer limits for client-facing traffic.

## Configuration
The `values.yaml` file provides extensive configuration options:

### General Settings
*   **`fullnameOverride`**: Overrides the full name of the chart.
*   **`gatewayRef`**: Specifies the Kubernetes Gateway API Gateway to which these policies apply (e.g., `public-gw`).
*   **`headers`**: Defines custom HTTP headers used for authorization and routing (`user`, `tier`, `tenant`, `model`).
*   **`denyByDefault`**: A boolean flag (default `true`) indicating that access is denied unless explicitly allowed by tier and model.

### AI Provider Configuration
*   **`providers`**: Configures AI service backends (e.g., `openai-team-a`, `google-team`). Each provider includes:
    *   `enabled`: Boolean to enable/disable the provider.
    *   `type`: Type of AI service (`openai`, `google`, `aws`).
    *   `schema`: API schema (e.g., `OpenAI`, `GCPVertexAI`).
    *   `endpoints`: List of FQDNs and ports for the service.
    *   `auth`: Authentication details, including `secret_name` for Kubernetes secrets, `projectName` (for Google), and `region` (for Google/AWS).
*   **`models`**: A list mapping logical model names (e.g., `gpt-5`, `gemini-2.5-pro`) to their respective `backend` providers.

### Security and TLS Policies
*   **`tlsPolicies`**: Configures TLS validation for backend connections, including `wellKnownCACertificates` and `hostname`.
*   **`security`**: Configures external authorization (`extAuth`) to integrate with the `lightbridge-authz` service (via `grpc-ext-auth` on port 3001) and specifies headers to forward.

### Rate Limiting and Traffic Management
*   **`rateLimitPolicies`**: Defines global rate limits for `requests` and `tokens`, with `perMin` and `perMonth` settings, and optional `cost` tracking.
*   **`tiers`**: Defines different user access tiers (`free`, `employee`, `developer`, `guru`), each with:
    *   `allow`: A list of allowed models (or `"*"` for all).
    *   `reqPerMin`, `tokensPerMin`, `reqPerMonth`, `tokensPerMonth`: Specific rate limits for each model within the tier.
*   **`localBurst`**: Configures a local token bucket rate limiter per Envoy pod.
*   **`exposeHeaders`**: Defines response headers to expose to clients (e.g., `x-lightbridge-tier`, `x-lightbridge-tenant`, `x-fallback-model`).
*   **`security`**: Configures external authorization (`extAuth`) to integrate with the `lightbridge-authz` service (via `grpc-ext-auth` on port 3001) and specifies headers to forward.
*   **`retry`**: Defines retry policies for backend requests, including `numAttemptsPerPriority`, `numRetries`, `perRetry` settings (back-off, timeout), and `retryOn` conditions (HTTP status codes, triggers).
*   **`clientTraffic`**: Configures client-facing traffic policies, such as `enableProxyProtocol`, `tcpKeepalive` settings, and `connection.bufferLimit`.

## Dependencies
The `lightbridge-config` chart has a Helm chart dependency on `common` from `https://charts.bitnami.com/bitnami`.

## External Dependencies
The `lightbridge-config` chart relies on the following external components:
1.  **Kubernetes Gateway API**: A Kubernetes Gateway API Gateway (e.g., `public-gw`) must be deployed and configured in the cluster.
2.  **AI Service Providers**: External AI services (e.g., OpenAI, Google Vertex AI) must be accessible from the cluster.
3.  **Kubernetes Secrets**: Secrets containing API keys or credentials for AI providers must exist in the cluster.
4.  **Lightbridge Authorization Service (`lightbridge-authz`)**: The `lightbridge-authz` service must be deployed and accessible as a gRPC endpoint (`grpc-ext-auth`) for external authorization to function.
5.  **Service Mesh / API Gateway**: An underlying service mesh (like Envoy Proxy with AI Gateway extensions) or an API Gateway capable of consuming the generated custom resources (e.g., `AIServiceBackend`, `Backend`, `SecurityPolicy`, `BackendTLSPolicy`, `BackendTrafficPolicy`, `AIGatewayRoute`, `ClientTrafficPolicy`) is required to enforce the policies defined by this chart.

## Interaction with other Lightbridge Charts
The `lightbridge-config` chart is deployed as a sub-chart of `lightbridge-authz-umbrella` and directly interacts with `lightbridge-authz`.
*   **`lightbridge-authz-umbrella`**: This umbrella chart orchestrates the deployment of `lightbridge-config` and can provide global configurations or specific overrides for its values.
*   **`lightbridge-authz`**: `lightbridge-config` is configured to use `lightbridge-authz` as its external authorization provider. This means that the service mesh/API Gateway, configured by `lightbridge-config`, will forward authorization requests to `lightbridge-authz` for evaluation before allowing traffic to AI backends.

## Testing Requirements
Testing `lightbridge-config` involves deploying the chart and verifying that the generated Kubernetes Custom Resources correctly configure the service mesh/API Gateway to enforce the defined policies. This includes:
*   **AI Provider Connectivity**: Ensuring that the `AIServiceBackend` and `Backend` resources correctly point to and authenticate with the external AI services.
*   **Authorization Enforcement**: Verifying that the `SecurityPolicy` (for external authz) and `guard-securitypolicy` (for RBAC based on tiers and models) correctly restrict access.
*   **Rate Limiting**: Confirming that `BackendTrafficPolicy` resources for global and local rate limits are applied and function as expected.
*   **Routing**: Ensuring `AIGatewayRoute` correctly routes requests based on the model header.
*   **TLS Enforcement**: Validating that `BackendTLSPolicy` secures communication with AI backends.

A full test setup would require a running Kubernetes cluster with the Gateway API, the `lightbridge-authz` service, and configured AI provider secrets.