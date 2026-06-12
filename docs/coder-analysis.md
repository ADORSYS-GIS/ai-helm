# Coder Capability & Architecture Analysis

**Date:** June 12, 2026  
**Author:** AI Governance Team  
**Status:** Draft for Review  
**Ticket:** #339 (Spike: Understand Coder capabilities and architecture)  
**Context:** Evaluation of Coder for integration into the **Converse** AI platform (LibreChat, Envoy Gateway ecosystem).

---

## 1. Executive Summary

**Recommendation:** **Proceed with Production Deployment.**  

Coder provides a robust platform for standardizing development environments, accelerating onboarding, and enabling secure, isolated AI agent workflows. Its architecture enables **self-service** infrastructure provisioning via Terraform templates, decoupling the "control plane" (Coder Server) from the "data plane" (Workspaces).

### Key Findings from Investigation

| Finding | Status | Details |
|---------|--------|---------|
| OpenCode Integration | ✅ Working | OpenCode runs successfully inside Coder workspaces via the `coder-labs/opencode` module |
| Health Check Issues | ✅ Resolved | Fixed invalid `small_model: null` configuration and model name format |
| Authentication | ✅ Working | OAuth2 authentication via `opencode auth login` command works in workspace terminal |
| VS Code Remote | ✅ Supported | Works seamlessly with OpenCode inside workspaces |
| Permission System | ✅ Configurable | `ask` for interactive approval, `allow` for autonomous |

### Key Value Propositions

*   **Instant Onboarding:** Reduces environment setup from days to minutes.
*   **AI Agent Orchestration:** Provides ephemeral, GPU-enabled sandboxes for AI agents (like OpenCode) to run code, test, and self-heal.
*   **Security:** Network-isolated workspaces prevent lateral movement from compromised environments to internal AI platforms.
*   **Cost Efficiency:** Ephemeral workspaces (stop/start) reduce cloud spend compared to always-on VMs.

### Primary Risk

The learning curve for **Terraform** (Template authoring) requires a dedicated Platform Engineer or DevOps resource. It is not a "zero-config" solution for end-users.

---

## 2. Architecture Deep Dive

Coder operates on a **Control Plane / Data Plane** architecture.

### 2.1 Core Components

| Component | Role | Deployment Location |
| :--- | :--- | :--- |
| **Coder Server** | The "Brain." Hosts UI, API, Auth, and runs Terraform. | **Kubernetes Cluster** (as a Pod). |
| **Template** | The "Blueprint." Terraform code defining OS, resources, and startup scripts. | Git Repository (pushed to Server). |
| **Workspace** | The "Worker." The actual compute resource (Pod, VM, or Container). | **Kubernetes Cluster** (as a Pod) or External Cloud (AWS/GCP). |
| **Coder Agent** | The "Bridge." Runs *inside* the workspace, connects outbound to Server. | Inside the Workspace. |
| **OpenCode** | The "AI Agent." Runs inside workspace, processes tasks via agentapi. | Inside the Workspace. |

### 2.2 Architecture Diagram

![Coder Architecture](./images/coder-architecture.png)

*The diagram above illustrates the complete Coder architecture:*

- **User Layer:** VS Code, Browser, and CLI clients connecting to Coder
- **Control Plane:** Coder Server with Web UI, API, Terraform Runner, and PostgreSQL database
- **Data Plane:** Kubernetes cluster running workspace pods containing Coder Agent, OpenCode, and Dev Tools
- **External Services:** AI APIs, Git providers, and OAuth2 servers for authentication

**Key Data Flows:**
- VS Code connects to Coder Agent via SSH/WebSocket tunnel
- Browser connects to Web UI via HTTPS
- Coder Agent makes outbound connections to API (no inbound firewall needed)
- OpenCode communicates with external AI APIs, Git providers, and OAuth2 servers

### 2.3 Integration with Converse Stack

*   **Envoy Gateway:** Coder workspaces can be configured with specific egress policies. If the workspace needs to talk to internal services, a `NetworkPolicy` must explicitly allow traffic.
*   **LibreChat:** AI agents running inside workspaces can access the LibreChat API via internal K8s service DNS (e.g., `http://librechat-service:3000`), provided network policies allow it.
*   **Security:** The Coder Agent uses **outbound-only** connections, meaning no firewall ports need to be opened on the cluster for incoming workspace traffic.

---

## 3. VS Code Remote Integration

### 3.1 How VS Code Remote Works with Coder

VS Code Remote is **essential** for interactive development. When you connect via VS Code Remote, you're editing files **inside** the workspace, not on your local machine.

![VS Code Remote Architecture](./images/vscode-remote-architecture.png)

*The diagram above illustrates:*
- *Your laptop runs VS Code (Editor Window)*
- *VS Code Extension connects to Coder workspace via SSH tunnel*
- *Files exist only in the workspace (/home/coder/project)*
- *OpenCode runs inside workspace, sees same files as VS Code*
- *Both edit the same remote filesystem*

### 3.2 Why VS Code Remote is Essential

| Use Case | Why VS Code Remote |
|----------|-------------------|
| **Interactive Coding** | Edit files, run terminals, debug code in the workspace |
| **Using OpenCode Interactively** | Run `opencode run "help me refactor"` in terminal; see results in real-time |
| **Debugging** | Set breakpoints, inspect variables, all in the workspace |
| **Extension Compatibility** | Most VS Code extensions work remotely without modification |
| **File Synchronization** | VS Code handles syncing files between local and remote automatically |

### 3.3 VS Code Remote vs. Coder Tasks

| Feature | VS Code Remote (Human) | Coder Task (AI Agent) |
|---------|----------------------|----------------------|
| **Who uses it?** | Humans | Automated AI agents |
| **When used?** | During development | For autonomous tasks |
| **Persistence?** | Yes, workspace stays | Ephemeral, destroyed after |
| **Interaction?** | Real-time editing | Pre-defined tasks |
| **Purpose?** | "I want to code" | "Run this task automatically" |

### 3.4 Can OpenCode Access Local Files?

**No, OpenCode in the Coder workspace cannot directly access files on your host machine.** The workspace is completely isolated - it runs as a Kubernetes Pod.

Files get into the workspace through:
1. **Git Clone** - Clone repository inside workspace
2. **VS Code Remote** - Open folder in VS Code, files sync to workspace
3. **PVC** - Persistent storage attached to workspace

---

## 4. OpenCode Integration in Coder

### 4.1 Running OpenCode Inside Coder Workspaces

OpenCode runs inside the workspace pod, providing AI assistance for coding tasks. The integration uses the `coder-labs/opencode` Terraform module.

**Key Configuration Findings:**

| Issue | Resolution |
|-------|------------|
| `small_model: null` causes crash | Remove from config or set to valid model name |
| Model name format `provider/model` | Use correct format in `models` block (e.g., `qwen-3-5-4b-local` not `camer/qwen-3-5-4b-local`) |
| API Key vs OAuth2 | OAuth2 preferred for production; API key works for testing |

### 4.2 Authentication Setup

For production use with OAuth2:

1. **In VS Code Remote terminal** (or Coder shell), run:
   ```bash
   opencode auth login
   ```

2. **Follow the device code flow**:
   - A browser URL will be displayed
   - Visit the URL and enter the device code
   - Authenticate with your credentials
   - Token is stored automatically

3. **Token refresh** happens automatically (configured via OAuth2 issuer)

The authentication configuration in your Terraform template should point to your OAuth2 issuer:

```hcl
provider = {
  camer = {
    options = {
      oauth2 = {
        authFlow = "device_code"
        clientId = "opencode-cli"
        issuer   = "https://auth.verif.fyi/realms/camer-digital"
        scopes   = ["openid", "profile", "offline_access"]
      }
    }
  }
}
```

### 4.3 OpenCode Permission System

OpenCode has a configurable permission system for controlling actions:

```hcl
permission = {
  edit = "ask"    # Ask before editing files (interactive)
  bash = "allow"  # Allow bash commands without prompting (autonomous)
}
```

| Setting | Use Case |
|----------|----------|
| `edit = "ask"` | Interactive development - user approves each file change |
| `edit = "allow"` | AI tasks - allow autonomous file modifications |
| `bash = "ask"` | Security-sensitive environments |
| `bash = "allow"` | Trusted CI/CD or autonomous agents |

### 4.4 OpenCode Health Check Architecture

![OpenCode Health Check](./images/opencode-health-check.png)

*The diagram above shows the health check flow:*
- *Coder Server initiates health check via Coder Agent*
- *Coder Agent queries agentapi on port 3284*
- *agentapi proxies to opencode process*
- *Response: status "running" if healthy*

**Common Health Check Issues:**

1. **Port 3284 not listening** - agentapi server not started
2. **OpenCode crashes** - Invalid configuration (e.g., `small_model: null`)
3. **Authentication failed** - API key invalid or OAuth2 token expired

### 4.5 When to Use Coder + OpenCode vs Direct OpenCode

| Criteria | Use Coder + OpenCode | Use Direct OpenCode |
|----------|---------------------|---------------------|
| Team size | > 1 developer | Solo |
| Environment complexity | Complex (multi-tool, GPU) | Simple (single language) |
| Infrastructure access | Need remote resources | Everything local |
| Data sensitivity | High (PII, production) | Low (personal) |
| Internet availability | Always connected | Intermittent/offline |
| Security requirements | Strict audit trail | Relaxed |
| GPU requirements | High (need cloud GPUs) | Standard |

---

## 5. Workspace Persistence Strategies

### 5.1 The Persistence Problem

Each Coder Task creates a **fresh workspace**, losing changes from previous sessions.

### 5.2 Solutions

#### Solution 1: Persistent Volume Claims (PVC)

```hcl
resource "kubernetes_persistent_volume_claim_v1" "workspace" {
  metadata {
    name      = "coder-${data.coder_workspace.me.id}-pvc"
    namespace = "coder"
  }
  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = { storage = "10Gi" }
    }
  }
}

# Mount in container
volume_mount {
  name       = "project-storage"
  mount_path = "/home/coder/project"
}
```

**Best for:** Long-running development workspaces

#### Solution 2: Git as Source of Truth (Recommended for AI Tasks)

```hcl
startup_script = <<-EOT
  cd /home/coder/project
  if [ ! -d ".git" ]; then
    git clone ${var.repo_url} .
  fi
  git config user.email "opencode@coder.local"
  git config user.name "OpenCode Agent"
EOT
```

**Best for:** AI agent tasks - each task clones latest, commits changes

#### Solution 3: Shared Storage (NFS/S3)

```hcl
volume {
  name = "shared-storage"
  nfs {
    server = "nfs-server.internal"
    path   = "/shared-projects"
  }
}
```

**Best for:** Team shared projects

---

## 6. Capabilities & Use Cases

### 6.1 Workspace Types

| Type | Description | Best For |
| :--- | :--- | :--- |
| **Standard Pod** | Lightweight container (Ubuntu/Alpine). | Web dev, scripting, API testing. |
| **GPU Workspace** | Pod with NVIDIA GPU passthrough. | Local LLM inference, AI model training. |
| **Multi-Container** | Pod with sidecars (e.g., DB, Redis). | Full-stack testing. |
| **Ephemeral Test** | Pod that self-destructs after task completion. | CI/CD, security scanning, one-off AI tasks. |
| **(Optional) VM** | Full VM via KubeVirt (if enabled). | Kernel modules, Windows, strict isolation. |

### 6.2 Good Use Cases for VS Code Remote + Coder

| Use Case | Why Coder Wins |
|----------|----------------|
| **Team Collaboration** | All developers use identical environments - no "works on my machine" issues |
| **Secure API Key Management** | API keys stored in K8s secrets, never on developer machines; rotated centrally |
| **Audit & Compliance** | All OpenCode sessions logged, tracked, and auditable via Coder's task reporting |
| **CI/CD Integration** | Workspace can be spun up as part of pipeline, run opencode tasks, and self-destruct |
| **GPU-on-Demand** | Same template can request GPU only when needed for heavy tasks |
| **Air-Gapped Security** | OpenCode runs in isolated namespace; can't exfiltrate code without explicit network policy |
| **Onboarding Speed** | New developer gets fully configured opencode workspace in ~2 minutes |
| **Resource Limits** | Prevent runaway opencode sessions from consuming all local CPU/RAM |

### 6.3 Bad Use Cases for VS Code Remote + Coder

| Use Case | Why NOT Use Coder |
|----------|-------------------|
| **Simple Script Editing** | Overhead of remote connection; VS Code local is faster |
| **Learning/Tutorial Work** | Need instant feedback; local environment simpler |
| **Offline Work Required** | Coder requires network connection |
| **Hardware-Specific Development** | iOS (requires Xcode/Mac), embedded systems (needs USB device access) |
| **Quick Prototyping** | Workspace startup time (even if 30 seconds); overkill for "just testing something" |
| **Large Media Files** | File sync latency is painful; better to work locally with cloud storage |

### 6.4 Key Features

*   **IDE Integrations:** Native support for **VS Code** (Extension), **JetBrains**, and **Browser-based** (code-server).
*   **Resource Management:** CPU/RAM limits enforced via K8s `ResourceQuota`.
*   **Persistent Storage:** `PersistentVolumeClaims` (PVC) ensure code survives workspace restarts.
*   **Parameters:** Users can customize workspaces (e.g., "Select Region," "Choose RAM") via a UI form without editing code.
*   **AI Agentic Workflow:** Coder can be triggered via API to spin up workspaces for AI agents to execute tasks, debug, and report back.

---

## 7. Security & Isolation Strategy

### 7.1 Namespace Isolation

Every workspace runs in its own K8s namespace (`workspace-<username>`).
*   **Network Policies:** Default deny all ingress/egress. Only allow traffic to explicitly whitelisted services.
*   **Prevention:** A compromised workspace cannot scan or attack other namespaces.

### 7.2 Resource Quotas

```yaml
# Example Quota per User
limits:
  cpu: "4"
  memory: "8Gi"
  pods: "10"
```

### 7.3 Pod Security Standards (PSS)

Enforce `restricted` mode:
*   No root users.
*   No host network/filesystem access.
*   No privileged containers.

### 7.4 Secrets Management

*   Secrets are injected at runtime via K8s Secrets or Vault.
*   Never baked into container images.
*   Scoped to the user's namespace.

---

## 8. Limitations & Gotchas

| Limitation | Impact | Mitigation |
| :--- | :--- | :--- |
| **Terraform Complexity** | Requires DevOps skills to create/maintain templates. | Dedicate 1 engineer to maintain templates; use pre-built community templates. |
| **No Native Windows** | Cannot run Windows workspaces without VMs (KubeVirt) or external cloud. | Use external cloud (AWS/Azure) templates for Windows needs. |
| **Nested Virtualization** | Running K8s *inside* a workspace requires KubeVirt and nested VM support. | Use K8s-in-K8s (K3s) inside Pod if full VM is not strictly required. |
| **Startup Latency** | First start of a new image takes time (pulling layers). | Use "Golden Images" (pre-built) and cache layers. |
| **Kernel Access** | Containers share the host kernel. | Use KubeVirt (VMs) if kernel modules are required. |

---

## 9. Comparison with Alternatives

### 9.1 Coder vs. ONa (GitPod)

| Feature | **Coder (Self-Hosted)** | **ONa / GitPod (SaaS)** |
| :--- | :--- | :--- |
| **Hosting** | Self-hosted (Your K8s) | SaaS (Their cloud) |
| **Data Sovereignty** | 100% Your Control | Third-Party |
| **Cost Model** | Pay for infra only | Per-user/month |
| **AI Agent Integration** | Native API | Limited |
| **Setup Complexity** | High (Terraform, K8s) | Low (Instant) |

### 9.2 Coder vs. Local Development

| Feature | Coder | Local |
|----------|------|-------|
| Environment consistency | Enforced via templates | Manual |
| GPU access | On-demand cloud GPUs | Limited to local hardware |
| Security | Network-isolated, audited | Depends on local security |
| Setup time | Immediate (self-service) | Manual per developer |
| Offline work | Requires connectivity | Works offline |

---

## 10. Cost & Operational Analysis

### 10.1 Infrastructure Costs

*   **Server:** Low overhead (1-2 nodes).
*   **Workspaces:** Pay only for active time.
    *   *Example:* 4 vCPU / 8GB RAM @ ~€0.05/hr.
    *   *Savings:* If developers stop workspaces at 6 PM, savings are >60% compared to always-on VMs.
*   **Storage:** PVCs (Block storage) are charged per GB/month. Keep them small (10-20GB).

### 10.2 Operational Overhead

*   **Maintenance:** Coder Server updates (monthly). Template maintenance (as tools change).
*   **Monitoring:** Use K8s native monitoring (Prometheus/Grafana).
*   **Backup:** PVCs need backup strategy (Velero or native snapshots).

---

## 11. Conclusion & Recommendations

### 11.1 Final Recommendation

**Use Coder if:**
*   You need **secure, ephemeral, GPU-rich environments** that developers cannot replicate locally.
*   You want **AI agents to have direct, low-latency, secure access** to code and cluster resources.
*   You have the **K8s expertise** to harden the cluster (NetworkPolicies, RBAC, Quotas).

**Do NOT use Coder if:**
*   You just want "VS Code in the browser" for convenience (use GitHub Codespaces instead).
*   Your team is small and trusts their local environments.
*   You don't have a dedicated DevOps/SRE person.

### 11.2 Specific Recommendations for OpenCode

1.  **Use OAuth2 authentication** - Run `opencode auth login` in workspace terminal for production
2.  **Configure permissions** (`edit = "ask"`, `bash = "allow"`) for appropriate security
3.  **Use Git as source of truth** for AI tasks to persist changes
4.  **Combine with VS Code Remote** for interactive development

### 11.3 Key Lessons from Investigation

1.  **OpenCode configuration must be valid JSON** - `null` values cause crashes
2.  **Model names must match provider format** - `provider/model` in top-level, `model` in models block
3.  **Health checks require agentapi running** - port 3284 must be listening
4.  **VS Code Remote and Coder Tasks are complementary** - not mutually exclusive

---

## Image Placeholders

The following images should be created and placed in `docs/images/`:

1. **coder-architecture.png** - Architecture diagram showing Control Plane / Data Plane split, user connection flow, and workspace components
2. **vscode-remote-architecture.png** - Diagram showing how VS Code Remote connects to workspace, file access flow
3. **opencode-health-check.png** - Health check flow between Coder Server, Coder Agent, agentapi, and opencode