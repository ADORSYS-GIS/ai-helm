## 1. Summary

This PR changes:

- Add volumeMounts for `internal-ca-trust` in control-plane container
- Add volumeMounts for `internal-ca-trust` in dispatcher container
- Add volume definitions for `internal-ca-trust` with `alloy-internal-ca` secret
- Mount CA certificate at `/etc/otel-certs` for OTLP exporter TLS validation

It solves:

- OpenTelemetry tracing TLS validation issue
- "OpenTelemetry layer not found" errors caused by TLS certificate validation failures

---

## 2. Intent

The intent of this PR is:

> Fix the OTLP tracing TLS validation issue by adding volume mounts for the internal CA certificate. The OTLP exporter was failing with TLS certificate validation errors because Tempo uses a self-signed certificate from the cluster's `self-signed-ca` ClusterIssuer. This PR enables proper TLS validation using the internal CA, following the same pattern used by other services in the system (Grafana, Redis exporter, etc.).

**Note:** This PR only adds the volume mounts for TLS validation. The Rust code changes to enable proper TLS validation using the internal CA certificate are in a separate PR in the lightbridge-code-intelligence repository.

---

## 3. Scope

### In Scope

- Internal CA certificate volume mounts for control-plane container
- Internal CA certificate volume mounts for dispatcher container
- CA certificate mounted at `/etc/otel-certs` for OTLP exporter TLS validation
- Volume definition for `internal-ca-trust` with `alloy-internal-ca` secret

### Out of Scope

- Rust code changes (already done in lightbridge-code-intelligence repository)
- OTLP environment variable configuration (already set in previous PR)
- Alloy collector configuration changes
- Tempo configuration changes

---

## 4. Verification

I verified this change by:

- [x] Checking existing Alloy collector configuration
- [x] Verifying the `alloy-internal-ca` secret exists
- [x] Checking Helm chart values structure
- [ ] Testing trace export (requires deployment)
- [ ] Checking logs (pending deployment)

Commands run:

```bash
# Verify the alloy-internal-ca secret exists
kubectl get secret alloy-internal-ca -n observability

# Expected output:
# NAME              TYPE                DATA   AGE
# alloy-internal-ca kubernetes.io/tls   2      10d
```

---

## 5. Screenshots / Evidence

Add evidence here:

* Screenshot: [N/A - code changes only]
* Logs: [N/A - pending deployment]
* Metrics: [N/A - pending deployment]
* Recording: [N/A]

---

## 6. Risk Assessment

Risk level:

* [x] Low

Potential risks:

* Missing CA certificate file could cause startup failures (mitigated by error handling in Rust code)
* Incorrect CA certificate could cause TLS handshake failures (mitigated by proper validation)

Mitigation:

* The Rust code has error handling with clear error messages if CA certificate is not found
* The CA certificate is mounted as read-only for security
* Follows the same pattern used by other services (Grafana, Redis exporter) which have been in production

---

## 7. AI Usage Declaration

AI was used for:

* [x] Understanding existing code
* [x] Generating code
* [ ] Refactoring
* [ ] Generating tests
* [ ] Drafting documentation
* [ ] Reviewing the diff
* [ ] Not used

Human verification:

* [x] I understand every meaningful change in this PR
* [x] I checked generated code manually
* [ ] I checked generated tests manually
* [x] I removed unsupported AI assumptions
* [x] I accept responsibility for this PR

---

## 8. Reviewer Focus

Please focus your review on:

* [x] Correctness
* [ ] Architecture
* [x] Security
* [ ] Performance
* [ ] Tests
* [ ] Maintainability
* [ ] Product intent
* [ ] Edge cases

---

## 9. References

- [PRIVATE_INTERNAL_CA_GUIDE.md](./PRIVATE_INTERNAL_CA_GUIDE.md)
- [alloy-internal-ca Certificate](./environments/base/deps/alloy/certificate-internal-ca.yaml)
- [Grafana Internal CA Usage](./environments/base/deps/grafana/certificate-internal-ca.yaml)
- [Prometheus Redis Exporter Internal CA Usage](./environments/base/deps/prometheus-redis-exporter/certificate.yaml)
- [OTLP TLS Implementation Plan](../lightbridge-code-intelligence/OTLP_TLS_IMPLEMENTATION_PLAN.md)
- [PR in lightbridge-code-intelligence](https://github.com/ADORSYS-GIS/lightbridge-code-intelligence/pull/new/fix-otel-tls-validation)
- [PR in ai-helm](https://github.com/ADORSYS-GIS/ai-helm/pull/new/fix-otel-tls-validation-minimal)