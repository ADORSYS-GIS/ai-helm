# converse-frontend

This chart deploys the Converse Frontend UI (static web app served by nginx).

## Required runtime configuration

The frontend reads a runtime configuration from `GET /config.json` (generated from a template at container startup).
The UI validates this payload and will fail to load if required fields are missing.

Provide the following values at install/upgrade time.

### Option A: values file

Create `my-values.yaml`:

```yaml
conversefrontend:
  controllers:
    main:
      containers:
        frontend:
          env:
            EXPO_PUBLIC_BACKEND_URL: "https://your-backend.example.com/"
            EXPO_PUBLIC_KEYCLOAK_ISSUER: "https://keycloak.example.com/realms/your-realm"
            EXPO_PUBLIC_KEYCLOAK_CLIENT_ID: "converse-ui"
            EXPO_PUBLIC_KEYCLOAK_SCHEME: "https"
```

Install/upgrade:

- `helm upgrade --install -n ai converse-frontend ./charts/converse-frontend -f my-values.yaml`

### Option B: --set flags

- `helm upgrade --install -n ai converse-frontend ./charts/converse-frontend \
  --set conversefrontend.controllers.main.containers.frontend.env.EXPO_PUBLIC_BACKEND_URL=https://your-backend.example.com/ \
  --set conversefrontend.controllers.main.containers.frontend.env.EXPO_PUBLIC_KEYCLOAK_ISSUER=https://keycloak.example.com/realms/your-realm \
  --set conversefrontend.controllers.main.containers.frontend.env.EXPO_PUBLIC_KEYCLOAK_CLIENT_ID=converse-ui \
  --set conversefrontend.controllers.main.containers.frontend.env.EXPO_PUBLIC_KEYCLOAK_SCHEME=https`


