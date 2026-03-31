# Gemini Thought Signature Patch - Removal Guide

This document describes how to remove the temporary Gemini thought signature patch once LiteLLM includes the fix in an official release.

## What the Patch Does

The patch is a LiteLLM Custom Logger/Hook that intercepts OpenAI-formatted requests before they are sent to Vertex AI (Google's Gemini API). It fixes known Gemini 3 reasoning signature bugs without modifying core LiteLLM logic.

### The Four Fixes

**Fix 1: Drop Empty Content**
- Prevents LiteLLM from generating an artificial empty text part
- Avoids triggering Gemini's strict "consecutive model turns" rejection

**Fix 2: Universally Bypass Cryptographic Signature Checks**
- Overwrites all incoming strict hashes with the Vertex bypass string (`skip_thought_signature_validator`)
- Handles signatures in `provider_specific_fields`, `server_side_tool_invocations`, and tool call IDs

**Fix 3: Handle Roo Code's Native thinking_blocks Signature Tracking**
- Processes signatures stored in `thinking_blocks` differently from other formats
- Ensures those signatures are also bypassed

**Fix 4: Prevent Duplicate Unsigned tool_calls**
- If thinking_blocks with a signature exists, it often implies the tool call is already inside it
- Removes duplicate top-level tool_calls to avoid Gemini "mixed support" errors

## Background

The patch was created to fix "Corrupted thought signature" errors when using Gemini 3 reasoning models (like `gemini-3-pro-preview`) with the LiteLLM proxy. The issue occurred because:

1. Roo Code (the client) stores thought signatures in tool call IDs with the format `call_xxx__thought__SIGNATURE`
2. LiteLLM passed these signatures directly to Google's Gemini API
3. Google's API expects signatures to be validated or replaced with special bypass strings

The patch intercepts requests and replaces signatures with `"skip_thought_signature_validator"` to bypass validation.

## Patch Components in values.yaml

The patch is configured in `charts/models-proxy/values.yaml` under the `proxy.persistence` section:

```yaml
proxy:
  persistence:
    # Gemini thought signature patch - single flag controls entire lifecycle
    # This is the single source of truth for enabling/disabling the patch.
    # When enabled: creates ConfigMap, mounts it, adds callback automatically
    # When disabled: removes all related config automatically
    gemini_patch:
      enabled: true
```

When enabled, the Helm chart automatically:
1. Creates the `litellm-gemini-plugin` ConfigMap with the patch code
2. Mounts the patch file into the LiteLLM container
3. Adds the callback to LiteLLM's configuration

## How to Remove the Patch

When LiteLLM releases a version that includes the fix, follow these steps:

### Step 1: Update LiteLLM Version

In `charts/models-proxy/values.yaml`, update the `global.litellm.version` to the version that includes the fix:

```yaml
global:
  litellm:
    version: "main-v1.XX.X"  # Use version with the fix
```

### Step 2: Disable the Patch in values.yaml

Set `proxy.persistence.gemini_patch.enabled: false` in `charts/models-proxy/values.yaml`:

```yaml
# Disable the Gemini patch - removes all related config automatically:
proxy:
  persistence:
    gemini_patch:
      enabled: false
```

When disabled, the chart automatically:
- Does NOT create the ConfigMap
- Does NOT mount the patch file
- Does NOT add the callback to LiteLLM's configuration

No other changes needed!

The updated values.yaml should look like:

```yaml
global:
  litellm:
    version: "main-v1.XX.X"  # Version with the fix
  configmap:
    name: "litellm-config"

proxy:
  service:
    litellm:
      enabled: true
      type: ClusterIP
      controller: litellm
      ports:
        http:
          enabled: true
          port: 4000
          targetPort: 4000

  controllers:
    litellm:
      type: deployment
      replicas: 1
      containers:
        litellm:
          image:
            repository: docker.litellm.ai/berriai/litellm
            tag: "{{ .Values.global.litellm.version }}"
          args:
            - --config
            - /app/config.yaml
          env:
            PUID: "1000"
            PGID: "1000"
            TZ: "Europe/Berlin"
            LITELLM_MODE: "production"
            REDIS_URL: "redis://redis-master.redis-system.svc.cluster.local:6379"
            OPENAI_API_KEY:
              secretKeyRef:
                name: openai-api-key
                key: apiKey
            GEMINI_API_KEY:
              secretKeyRef:
                name: gemini-api-key
                key: apiKey
          resources:
            limits:
              cpu: 1
              memory: 1Gi
            requests:
              cpu: 500m
              memory: 512Mi

  persistence:
    config:
      enabled: true
      type: configMap
      name: '{{ .Values.global.configmap.name }}'
      advancedMounts:
        litellm:
          litellm:
            - path: /app/config.yaml
              subPath: config.yaml
              readOnly: true
    # Gemini patch disabled - no ConfigMap or mount created
    gemini_patch:
      enabled: false

config:
  litellm_settings:
    cache: True
    cache_params:
      type: redis
      namespace: "litellm.caching.caching"
    # NO callbacks here - removed automatically when patch disabled

  model_list:
    - model_name: "gemini-3-pro-preview"
      litellm_params:
        model: "gemini/gemini-3-pro-preview"
        api_key: "os.environ/GEMINI_API_KEY"
```

That's it! The chart handles everything automatically - no manual ConfigMap deletion needed.

### Step 3: Redeploy

```bash
helm upgrade models-proxy charts/models-proxy -n models-proxy
```

### Step 4: Verify

```bash
# Check pod is running
kubectl get pods -n models-proxy -l app=proxy-app

# Check logs for any issues
kubectl logs -n models-proxy -l app=proxy-app
```

## Version Lookup

To find the version that includes the fix:

1. Check LiteLLM's GitHub releases: https://github.com/BerriAI/litellm/releases
2. Look for release notes mentioning:
   - "Gemini 3" / "thought signature"
   - "Gemini reasoning models"
   - "skip_thought_signature_validator"
3. Check LiteLLM Discord for announcements

## Quick Rollback Script

```bash
#!/bin/bash
# Remove Gemini patch when LiteLLM has the fix

NAMESPACE=models-proxy

# Delete the ConfigMap
kubectl delete configmap litellm-gemini-plugin -n $NAMESPACE --ignore-not-found

# Get current values.yaml path
VALUES_FILE="charts/models-proxy/values.yaml"

# Check if gemini_patch section exists
if grep -q "gemini_patch:" $VALUES_FILE; then
  echo "Found gemini_patch in values.yaml - please manually remove:"
  echo "  - persistence.gemini_patch section"
  echo "  - callbacks: [\"litellm_gemini_patch.proxy_handler_instance\"]"
  echo "Then run: helm upgrade models-proxy charts/models-proxy -n $NAMESPACE"
else
  echo "Patch sections already removed from values.yaml"
  helm upgrade models-proxy charts/models-proxy -n $NAMESPACE
fi
```

## Monitoring After Removal

After removing the patch, monitor for:

1. "Corrupted thought signature" errors in logs
2. Request failures with Gemini 3 models

```bash
kubectl logs -n models-proxy -l app=proxy-app | grep -i "corrupted\|signature"
```

If errors persist, you may need to:
- Wait for a newer LiteLLM version
- Or temporarily re-apply the patch (restore values.yaml + apply ConfigMap)
