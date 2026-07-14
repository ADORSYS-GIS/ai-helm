# HTTP Redirection: Why 308 Matters for APIs

This document explains the technical details behind the HTTP redirection issue we fixed in the `ai-gateway-core` chart.

## 1. The Core Issue: 301 vs. 308

When a client (like `curl`) makes a request to `http://` and receives a redirect to `https://`, the status code tells the client exactly how to behave.

### HTTP 301 (Moved Permanently)
*   **Legacy Behavior**: Originally, the spec said the method should be preserved. In practice, however, most browsers and clients (including `curl`) **change the method to GET** and drop the request body when following a 301 redirect.
*   **The Symptom**: Your `POST` request became a `GET` request on the second leg, leading to "method not allowed" or missing body errors.

### HTTP 308 (Permanent Redirect)
*   **Modern Behavior**: This code was specifically created to solve the ambiguity of 301. It **requires** the client to preserve the original HTTP method and body.
*   **The Result**: A `POST` remains a `POST`. This is essential for REST APIs.

## 2. The Discovery
We knew it was a redirection issue when your `curl -v` log showed:
```text
* Clear auth, redirects to port from 80 to 443
* Switch from POST to GET
```
This "Switch from POST to GET" is the hallmark behavior of a client following a 301 redirect.

## 3. The Implementation (Envoy Gateway)

### The Constraint
Envoy Gateway (EG) implements the Kubernetes Gateway API. While the spec allows `308`, the **Envoy Gateway controller (as of v1.7.0) only supports `301` and `302`** in its standard `RequestRedirect` filter.

### The Workaround: EnvoyPatchPolicy
Since we couldn't set `308` in the `HTTPRoute`, we had to go "under the hood" of the Envoy configuration (xDS) using an `EnvoyPatchPolicy`.

1.  **Inspection**: We used `kubectl port-forward` and a `config_dump` to see exactly how EG was configuring Envoy.
2.  **Mapping**: We found that the redirect routes were located in specific `virtual_hosts` indices (1 and 2).
3.  **Patching**: We applied a JSON Patch to override the generated Envoy configuration:
    ```yaml
    operation:
      op: add
      path: /virtual_hosts/1/routes/0/redirect/response_code
      value: "PERMANENT_REDIRECT" # This is Envoy's internal name for 308
    ```

## 4. The `curl` Security Behavior

Even with a 308, you noticed that the `Authorization` header was initially missing in the second request.

### Why `curl` drops headers
By default, `curl` is highly protective of your credentials. When it follows a redirect that changes the **origin** (even just a protocol change from `http` to `https`), it strips sensitive headers like `Authorization` to prevent them from being sent to a potentially malicious redirected destination.

### The Fix: `--location-trusted`
The `--location-trusted` flag tells `curl` that you trust the redirected destination and want it to reuse the original credentials and headers.

## Summary Checklist for API Redirects
1.  **Use 308**: Always use 308 for internal HTTP -> HTTPS redirects in APIs.
2.  **Avoid 80**: Ideally, API clients should talk directly to 443 (HTTPS) to avoid the redirect trip entirely.
3.  **HSTS**: Consider enabling strict-transport-security (HSTS) headers so the client's OS remembers to use HTTPS automatically for future requests.
