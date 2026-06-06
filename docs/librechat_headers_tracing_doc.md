# Configuring and Tracing LibreChat & MCP Headers via Envoy

This guide documents how to inject user session information as custom HTTP headers into Model Context Protocol (MCP) servers and upstream endpoints via LibreChat, and how to verify propagation using Envoy Gateway logs.

---

## 1. Injecting Headers in `values.yaml`

LibreChat supports passing internal session variables via custom API headers. Inside your `values.yaml` (under the `librechat` chart configuration), you can declare an `mcpServers` or `custom` endpoints block. 

### Configuration Example

Here is how you can pass the relevant user information down to downstream endpoints/MCPs:

![alt text](./images/image-10.png)

```yaml
    lightbridge_self_service:
      title: "LightBridge API KEYs"
      description: "LightBridge Self Service API-KEYs"
      type: "streamable-http"
      url: "https://mcp.ai.camer.digital/mcp"
      headers:
        X-ACCOUNT-ID: 'LIBRECHAT'
        # These variables are substituted by LibreChat using its internal user record
        X-PROJECT-ID: 'sso:{{ `{{` }}LIBRECHAT_USER_OPENIDID{{ `}}` }}'
        X-USER-ID: '{{ `{{` }}LIBRECHAT_USER_ID{{ `}}` }}'
        X-USER-EMAIL: '{{ `{{` }}LIBRECHAT_USER_EMAIL{{ `}}` }}'
        X-USER-ROLE: '{{ `{{` }}LIBRECHAT_USER_ROLE{{ `}}` }}'
```

> [!IMPORTANT]
> Because we deploy via Helm, you must escape the double curly braces `{{ }}` natively expected by LibreChat so that Helm does not evaluate them during template processing. Use the `{{ `{{` }} ... {{ `}}` }}` trick shown above.

---

## 2. Understanding Variable Provenance

It is critical to distinguish between LibreChat's **internal variables** and **Keycloak JWT claims**.

### LibreChat Internal Variables (`{{ LIBRECHAT_USER_... }}`)
When you use a placeholder like `{{LIBRECHAT_USER_ROLE}}`, the value is pulled from the **LibreChat MongoDB database**, not directly from the current OIDC Access Token.

*   **`LIBRECHAT_USER_ROLE`**: This identifies the user's role within the LibreChat application (e.g., `ADMIN` or `USER`). By default, LibreChat assigns `ADMIN` to the first user created and `USER` to everyone else. It does **not** automatically sync with Keycloak roles.
*   **`LIBRECHAT_USER_EMAIL` / `ID`**: These are initially populated from Keycloak during the first login (OIDC registration) but are subsequently served from the internal user profile record.

### Keycloak Roles (Authorino Injection)
If your downstream MCP server requires the **true roles defined in Keycloak** (e.g., `beta-tester`, `mcp-access`), LibreChat's internal substitution cannot provide them. 

Instead, you should leverage the **Envoy Gateway & Authorino** to inject these claims. Because LibreChat forwards the Bearer token to the gateway, Authorino can extract the `librechat_roles` claim and inject it into a new header:

```yaml
# Inside security-policies in apps/values.yaml
authConfigs:
  main:
    response:
      success:
        headers:
          "x-keycloak-roles":
            plain:
              selector: "auth.identity.librechat_roles"
```

For more details on OIDC mapping, see:
- [LibreChat OIDC Integration with Keycloak](./librechat-oidc-integration.md)
- [LibreChat OIDC Experiments](./librechat-oidc-experiments.md)

---

## 3. Tracing Headers in Envoy (Production)

To verify that headers (internal or injected) are successfully attached in **production**, you must set Envoy's routing logs to `debug` level.

### Enabling Debug Logging
Modify your Envoy Gateway configuration in `apps/values.yaml` and sync via ArgoCD:

```yaml
eg:
  config:
    envoyGateway:
       logging:
         level:
           default: debug  # Change to debug for tracing
```

### Analyzing the Trace
Monitor the Envoy proxy logs using `kubectl` or your centralized logging stack:

```bash
kubectl logs -l app.kubernetes.io/name=envoy -n converse-gateway -c envoy --tail=200 -f
```

![alt text](./images/image-12.png)

When a request is processed, you will see Envoy decoding the headers:

```text
[debug][router] ... router decoding headers:
':authority', 'envoy-converse-gateway-core-gateway-c480b207.envoy-gateway-system.svc.cluster.local'
...
'x-user-role', 'ADMIN'  <-- Internal LibreChat Role
'x-keycloak-roles', '["user", "beta-tester"]' <-- Injected by Authorino
```

---

## 4. Best Practices
*   **Performance**: Always revert Envoy's logging level to `warn` after verification to avoid log bloat and performance degradation.
*   **Security**: Do not pass sensitive internal metadata to untrusted or external MCP servers. Use HTTPS for all upstream connections.
