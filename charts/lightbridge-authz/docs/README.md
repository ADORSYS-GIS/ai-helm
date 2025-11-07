# Lightbridge Authorization Service (lightbridge-authz)

## Purpose
The `lightbridge-authz` Helm chart deploys the core Lightbridge authorization service. This service is responsible for handling all authorization requests within the Lightbridge ecosystem. It validates incoming requests against policies (likely defined by the `lightbridge-config` chart) and provides authorization decisions to the service mesh or API gateway. It exposes both a REST and a gRPC interface.

## Architecture
The chart utilizes an init container to dynamically generate its configuration. This init container reads sensitive values like `DATABASE_URL` and `JWKS_URL` from Kubernetes secrets and a configuration template from a ConfigMap. It then replaces placeholders in the template with the actual values and writes the final configuration file, which the main authorization service container uses.

## Configuration
The primary configuration for `lightbridge-authz` is managed via its `values.yaml` file, which leverages the `app-template` Helm chart for common application patterns. Key configurable aspects include:

*   **Image**: The Docker image for the authorization service (`ghcr.io/franck-sorel/lightbridge-authz`).
*   **Ports**: The service exposes HTTP on port 3000 and gRPC on port 3001.
*   **Persistence**:
    *   `secrets`: Mounts a Kubernetes secret named `lightbridge-authz-secrets` to `/secrets`, expecting `DATABASE_URL` and `JWKS_URL`.
    *   `config-template`: Mounts a ConfigMap named `config-template` to `/config-template`, containing `config.yaml` with placeholders.
    *   `config`: An `emptyDir` volume mounted to `/config` where the generated `config.yaml` is stored.
*   **ConfigMap Data**: The `config-template` ConfigMap defines the base configuration structure, including:
    *   `server.rest.address` and `server.rest.port`
    *   `server.grpc.address` and `server.grpc.port`
    *   `logging.level`
    *   `database.url`: Placeholder `{{DATABASE_URL}}`
    *   `database.pool_size`
    *   `oauth2.jwks_url`: Placeholder `{{JWKS_URL}}`

## Dependencies
The `lightbridge-authz` chart has the following Helm chart dependencies:
*   `common` (from `https://charts.bitnami.com/bitnami`)
*   `app-template` (from `https://bjw-s-labs.github.io/helm-charts`)

## External Dependencies
The `lightbridge-authz` service requires the following external services to function correctly:
1.  **PostgreSQL Database**: A PostgreSQL database instance is required, and its connection string must be provided via the `DATABASE_URL` secret.
2.  **OAuth2/OIDC Provider (e.g., Keycloak)**: An OAuth2/OIDC provider is needed to issue and manage tokens. The service validates these tokens using a JSON Web Key Set (JWKS) endpoint, whose URL must be provided via the `JWKS_URL` secret.

## Interaction with other Lightbridge Charts
The `lightbridge-authz` service is a core component of the Lightbridge authorization system. It is deployed by the `lightbridge-authz-umbrella` chart and is consumed by the `lightbridge-config` chart.
*   **`lightbridge-authz-umbrella`**: This umbrella chart is responsible for deploying `lightbridge-authz` as a sub-chart, providing global configurations and overrides.
*   **`lightbridge-config`**: The `lightbridge-config` chart configures the service mesh/API Gateway to use `lightbridge-authz` as an external authorization service. Requests coming into the gateway are forwarded to `lightbridge-authz` (via its gRPC interface on port 3001) for authorization decisions before being routed to AI backends.

## Testing Requirements
The chart includes a `test-connection.yaml` that uses a `busybox` pod to `wget` the service's HTTP endpoint (port 3000). This verifies basic network connectivity and service availability.

To fully test the `lightbridge-authz` service, the following external dependencies must be deployed and configured:
*   A running PostgreSQL database.
*   A running Keycloak (or compatible OAuth2/OIDC) instance with a configured realm and client, exposing its JWKS endpoint.

The `lightbridge-authz-secrets` Kubernetes secret must be created with the correct `DATABASE_URL` and `JWKS_URL` values pointing to these deployed services.

### Example External Configuration Manifests
You can find example Kubernetes manifests for a simple PostgreSQL database and Keycloak deployment in the `charts/lightbridge-authz/docs/external-config/` directory:
*   [`postgresql.yaml`](charts/lightbridge-authz/docs/external-config/postgresql.yaml)
*   [`keycloak.yaml`](charts/lightbridge-authz/docs/external-config/keycloak.yaml)

To deploy these for testing:
```bash
kubectl apply -f charts/lightbridge-authz/docs/external-config/postgresql.yaml
kubectl apply -f charts/lightbridge-authz/docs/external-config/keycloak.yaml
```

#### PostgreSQL PVC Requirements
The provided `postgresql.yaml` manifest includes a `PersistentVolumeClaim` named `postgres-pv-claim` requesting 1Gi of storage with `ReadWriteOnce` access mode. For this PVC to bind successfully, your Kubernetes cluster must have a default `StorageClass` configured or a `PersistentVolume` that can satisfy these requirements. If not, you might need to create a `StorageClass` or a `PersistentVolume` manually, or modify the PVC to specify an existing `StorageClass`.

#### Building `lightbridge-authz-secrets`
After deploying PostgreSQL and Keycloak, you need to create a Kubernetes secret named `lightbridge-authz-secrets` containing the `DATABASE_URL` and `JWKS_URL`.

**1. Determine `DATABASE_URL`:**
The PostgreSQL service deployed by the example manifest is named `postgres` in the same namespace. The connection string format is typically `postgresql://user:password@host:port/database`.
Using the values from `charts/lightbridge-authz/docs/external-config/postgresql.yaml`:
*   User: `authz_user`
*   Password: `authz_password`
*   Host: `postgres` (the service name)
*   Port: `5432`
*   Database: `authz_db`

So, your `DATABASE_URL` will be:
`postgresql://authz_user:authz_password@postgres:5432/authz_db`

**2. Determine `JWKS_URL`:**
The Keycloak service deployed by the example manifest is named `keycloak` in the same namespace. The JWKS endpoint URL depends on your Keycloak realm configuration. Assuming a realm named `master` (default) or `<your-realm>`, the typical format is `http://<keycloak-service-name>:<port>/realms/<your-realm>/protocol/openid-connect/certs`.
Using the values from `charts/lightbridge-authz/docs/external-config/keycloak.yaml`:
*   Keycloak Service Name: `keycloak`
*   Port: `8080`
*   Realm: You will need to configure a realm in Keycloak. Let's assume you create a realm named `lightbridge-realm`.

So, your `JWKS_URL` will be:
`http://keycloak:8080/realms/lightbridge-realm/protocol/openid-connect/certs`
(Remember to replace `lightbridge-realm` with your actual Keycloak realm name).

**3. Create the Kubernetes Secret:**
Once you have your `DATABASE_URL` and `JWKS_URL`, create the secret:
```bash
kubectl create secret generic lightbridge-authz-secrets \
  --from-literal=DATABASE_URL="postgresql://authz_user:authz_password@postgres:5432/authz_db" \
  --from-literal=JWKS_URL="http://keycloak:8080/realms/lightbridge-realm/protocol/openid-connect/certs"
```
(Remember to replace `lightbridge-realm` with your actual Keycloak realm name if different from `lightbridge-realm`).