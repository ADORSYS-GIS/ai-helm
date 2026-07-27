# Priorités de correction — Projet ai-helm

> **Date :** 2026-07-27  
> **Contexte :** Audit complet du projet ai-helm (GPU, sécurité, exploitation, legacy)  
> **Objectif :** Documenter tout ce qui est mal fait ou inachevé, et les étapes pour que le projet fonctionne correctement.

---

## Table des matières

1. [🔴 P0 — Critique : bloque l'exploitation propre](#-p0--critique--bloque-lexploitation-propre)
2. [🟡 P1 — Important : doit être fait avant le lancement utilisateur](#-p1--important--doit-être-fait-avant-le-lancement-utilisateur)
3. [🔵 P2 — Moyen : améliorations significatives](#-p2--moyen--améliorations-significatives)
4. [🟢 P3 — Secondaire : nettoyage et polish](#-p3--secondaire--nettoyage-et-polish)
5. [📋 Checklist de lancement](#-checklist-de-lancement)

---

## 🔴 P0 — Critique : bloque l'exploitation propre

### P0.1 — Containers GPU tournent en root

| Champ | Valeur |
|-------|--------|
| **Fichier** | `charts/model-server/values.yaml` |
| **Ligne** | `podSecurityContext.runAsUser: 0` |
| **Problème** | Les pods des modèles tournent avec `root`. Un attaquant qui casse le processus modèle a `root` dans le pod, ce qui facilite l'escalade vers le nœud GPU. |
| **Solution** | Passer à `runAsUser: 1000`, `runAsNonRoot: true`, `seccompProfile: RuntimeDefault` |
| **Risque** | `runAsUser: 1000` n'a jamais été testé sur un vrai GPU NVIDIA. Peut casser l'accès CUDA. |
| **Effort** | 2h (test sur 1 modèle d'abord) |
| **Issue** | `TODO` présent dans le code source |

**À faire :**
1. Modifier `charts/model-server/values.yaml` :
   ```yaml
   podSecurityContext:
     runAsUser: 1000          # au lieu de 0
     runAsNonRoot: true       # au lieu de false
     seccompProfile:
       type: RuntimeDefault
   ```
2. Déployer sur un seul modèle (ex: Qwen3-8B) dans un namespace de test
3. Vérifier que `/health` et `/metrics` répondent
4. Vérifier que DCGM voit toujours le GPU
5. Si OK → déployer sur tous les modèles

---

### P0.2 — Discord webhook non mis à jour

| Champ | Valeur |
|-------|--------|
| **Fichier** | AWS Secrets Manager → `ai/camer/digital/prod/env` |
| **Clé** | `grafana_discord_webhook_url` |
| **Problème** | Le webhook pointe encore vers le canal personnel du lead, pas vers le canal équipe. Les alertes GPU (température, VRAM, santé) ne sont visibles que par une seule personne. |
| **Solution** | Mettre à jour le secret AWS, et optionnellement garder l'ancien webhook sous une autre clé pour le lead |
| **Effort** | 15 min |

**À faire :**
1. Dans AWS Secrets Manager → `ai/camer/digital/prod/env` :
   - `grafana_discord_webhook_url` → URL du webhook du canal **team**
   - `grafana_discord_webhook_url_stephane` → URL du webhook perso (optionnel)
2. Optionnel : créer une deuxième alerte Discord dans `charts/observability-dashboards/` :
   ```yaml
   discord-stephane:
     enabled: true
     url: "${GRAFANA_DISCORD_WEBHOOK_URL_STEPHANE}"
   ```

---

### P0.3 — Z-Image-Turbo retourne HTTP 500

| Champ | Valeur |
|-------|--------|
| **Modèle** | `zimage-turbo` sur `admin@homeos` |
| **Cluster** | Legacy (`admin@homeos`) |
| **Problème** | Le seul modèle de génération d'image est cassé. Les utilisateurs qui appellent `/v1/images/generations` reçoivent une erreur 500. |
| **Solution** | Diagnostiquer ou désactiver |
| **Effort** | 1h (diag) / 15 min (désactivation) |

**À faire (diagnostic) :**
```bash
# Sur admin@homeos (cluster legacy) :
kubectl logs -n converse-poc deploy/model-serving-zimage-turbo

# Tester l'endpoint :
curl -X POST http://z-image-turbo--poc.ssegning.com/v1/images/generations \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"zimage-turbo","prompt":"hello"}'
```

**Si non réparable :** désactiver dans `charts/ai-models/values.yaml` :
```yaml
zimage-local-01:
  enabled: false
```

---

## 🟡 P1 — Important : doit être fait avant le lancement utilisateur

### P1.1 — Aucun load test réel effectué

| Champ | Valeur |
|-------|--------|
| **Problème** | Les benchmarks annoncés (OpenMythos 15 tok/s, Qwen3 45 tok/s) sont **prédits**, pas mesurés sous charge réelle. |
| **Impact** | On ne sait pas si un modèle tient 2, 5 ou 10 utilisateurs simultanés. Le continuous batching de vLLM n'est pas exercé. |
| **Solution** | Utiliser GuideLLM, NVIDIA aiperf ou inference-perf |
| **Effort** | 1-2j |

**À faire :**
```bash
# Dans inference-ops repo — outils recommandés :
# GuideLLM : patterns de conversation réels
# NVIDIA aiperf : benchmarks standardisés
# inference-perf : throughput/latence sous charge
```

Scénarios à tester :
| Modèle | Utilisateurs simultanés | Métrique cible |
|--------|------------------------|----------------|
| OpenMythos-27B | 1, 2, 5 | ≥ 12 tok/s, TTFT < 2s |
| Qwen3-8B-AWQ | 1, 5, 10 | ≥ 35 tok/s, TTFT < 1s |

---

### P1.2 — LMCache activé mais non vérifié

| Champ | Valeur |
|-------|--------|
| **Fichier** | `charts/model-serving/values.yaml` → `qwen3-8b-fast` |
| **Clé** | `lmcache.enabled: true` |
| **Problème** | vLLM avertit que LMCache désactive le cache manager hybride intégré. Aucun test A/B n'a été fait pour vérifier si c'est un gain ou une perte. |
| **Solution** | Test A/B : désactiver LMCache, comparer tok/s, TTFT, VRAM |
| **Effort** | 1j |

**À faire :**
1. Désactiver LMCache pour Qwen3-8B :
   ```yaml
   lmcache:
     enabled: false
   ```
2. Mesurer : tok/s, TTFT (time-to-first-token), VRAM usage
3. Comparer avec les mesures actuelles
4. Si pire sans → laisser `true`. Si meilleur sans → laisser `false`.
5. Documenter la décision dans une note ADR ou dans le fichier de valeurs.

---

### P1.3 — `/v1/models` expose des modèles inaccessibles

| Champ | Valeur |
|-------|--------|
| **Fichier** | `charts/ai-models/values.yaml` |
| **Problème** | Les modèles avec `disableExternal: true` apparaissent dans la liste `/v1/models` mais retournent 404 si un utilisateur les sélectionne. |
| **Solution** | Filtrer la réponse de `/v1/models` pour n'afficher que les modèles accessibles, OU documenter le comportement. |
| **Effort** | 30 min |

---

### P1.4 — Pas d'attribution coût → GPU

| Champ | Valeur |
|-------|--------|
| **Problème** | DCGM sait quel pod utilise quel GPU. La gateway sait combien chaque requête coûte. Rien ne relie les deux. |
| **Impact** | Impossible de savoir combien coûte réellement un modèle (GPU/hr vs revenus). |
| **Solution** | Dashboard Grafana qui joint DCGM (métriques GPU par pod) et Mimir (coût par requête modèle). |
| **Effort** | 2j |

**Piste :**
- DCGM : `DCGM_FI_DEV_FB_USED{pod="..."}` 
- Mimir : `ai_gateway_request_duration_ms{model="..."}` + `user_id`
- PromQL : joindre par `model` (tag ajouté aux métriques DCGM via le pod label)

---

## 🔵 P2 — Moyen : améliorations significatives

### P2.1 — Grafana stateless (emptyDir)

| Champ | Valeur |
|-------|--------|
| **Fichier** | `charts/observability-dashboards/` |
| **Problème** | Les dashboards sont stockés dans `emptyDir`. Tout changement de `grafana.ini` (ou restart du pod) les détruit. |
| **Solution** | Remplacer `emptyDir` par un PV (Longhorn) ou documenter la procédure de restauration. |
| **Effort** | 1h |

**Solution rapide :**
```bash
# Après un changement de config, NE PAS supprimer le pod Grafana.
# Au lieu de ça :
kubectl rollout restart -n observability deploy/grafana-operator
```

**Solution durable :**
```yaml
# Dans grafanavalues.yaml
persistence:
  enabled: true
  storageClassName: longhorn
  size: 10Gi
```

---

### P2.2 — Pas d'alerte de régression de performance

| Champ | Valeur |
|-------|--------|
| **Fichier** | `charts/observability-dashboards/` (alerting rules) |
| **Problème** | Il y a des alertes pour température GPU, VRAM, santé — mais rien qui prévient si un modèle devient soudainement 2× plus lent. |
| **Solution** | Ajouter une règle d'alerte Prometheus qui compare le token rate actuel à la moyenne des 7 derniers jours. |
| **Effort** | 1j |

**Règle Prometheus suggérée :**
```yaml
- alert: TokenRateRegression
  expr: |
    rate(vllm:prometheus_token_rate_total[5m])
    / avg_over_time(rate(vllm:prometheus_token_rate_total[5m])[7d:])
    < 0.8
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Le token rate de {{ $labels.model }} a chuté de plus de 20%"
```

---

## 🟢 P3 — Secondaire : nettoyage et polish

### P3.1 — 8 charts legacy qui encombrent le repo

| Fichier | Statut |
|---------|--------|
| `charts/model-serving-qwen3-4b/` | `enabled: false` |
| `charts/model-serving-qwen3-5/` | `enabled: false` |
| `charts/model-serving-deepseek-r1-1-5b/` | `enabled: false` |
| `charts/model-serving-qwen25-3b-awq/` | `enabled: false` |
| `charts/model-serving-qwen3-8b/` | `enabled: false` |
| `charts/model-serving-ministral-3b/` | `enabled: false` |
| `charts/model-serving-qwen2-vl-2b/` | `enabled: false` |
| `charts/model-serving-zimage-turbo/` | **`enabled: true`** (LIVE) |

**À faire :**
1. Décommissionner Z-Image-Turbo sur `admin@homeos`
2. Supprimer les 8 dossiers `charts/model-serving-*/`
3. Supprimer les 8 entrées dans `charts/apps/values.yaml`
4. Supprimer `homeCluster: true` (ADR-0022)
5. Supprimer la logique `homeCluster` si elle n'est plus utilisée nulle part

---

### P3.2 — ADR doublon (0077)

| Fichier | Problème |
|---------|----------|
| `docs/adr/0077-my-usage-dashboard.md` | ADR 0077 |
| `docs/adr/0077-phoenix-style-chat-dashboards.md` | ADR 0077 aussi ! |

**Solution :** Renuméroter le second en 0078 ou fusionner.

---

### P3.3 — `grafana.ini` changes → procédure documentée

Documenter dans `docs/operations/grafana-config-change.md` :
```bash
# Après modification de grafana.ini :
kubectl rollout restart -n observability deploy/grafana-operator

# Les dashboards seront conservés si persistence.enabled=true
# Sinon, re-sync ArgoCD manuellement
```

---

### P3.4 — Images engine non versionnées proprement

| Modèle | Image | Date |
|--------|-------|------|
| OpenMythos-27B | `llamacpp` | Non spécifié |
| Qwen3-8B-AWQ | `lmcache/vllm-openai:v0.5.2` | 2026-07-22 |

**Problème :** Pas de politique de mise à jour des images engine. Quand une nouvelle version CUDA ou vLLM sort, qui est notifié ?

**Solution :** Ajouter un renovate / dependabot pour les images Docker dans les valeurs Helm, ou documenter un cycle de mise à jour trimestriel.

---

## 📋 Checklist de lancement

### Avant de lancer les modèles aux utilisateurs

- [ ] **P0.1** — Containers non-root testés et déployés
- [ ] **P0.2** — Discord webhook mise à jour
- [ ] **P0.3** — Z-Image-Turbo réparé ou désactivé
- [ ] **P1.1** — Load tests passés (1 modèle validé)
- [ ] **P1.2** — LMCache A/B test fait
- [ ] **P1.3** — `/v1/models` filtré
- [ ] **P1.4** — Dashboard coût/GPU créé (minimal)

### Avant de merger en production

- [ ] `check-model-catalogs.sh` passe
- [ ] Les endpoints `/health` des 2 modèles répondent
- [ ] Un appel complet fonctionne :
  ```bash
  curl https://api.ai.camer.digital/v1/chat/completions \
    -H "Authorization: Bearer $(opencode auth token)" \
    -d '{"model":"openmythos-27b","messages":[{"role":"user","content":"Bonjour"}]}'
  ```
- [ ] Les alertes arrivent sur le bon canal Discord

### Post-lancement

- [ ] **P3.1** — Nettoyer les 8 charts legacy
- [ ] **P3.2** — Réparer le doublon ADR-0077
- [ ] **P3.3** — Documenter la procédure Grafana
- [ ] **P3.4** — Politique de mise à jour des images engine

---

## Vue d'ensemble

```mermaid
gantt
    title Planning de correction — ai-helm
    dateFormat  YYYY-MM-DD
    section 🔴 P0 — Critique
    Containers non-root            :p0_1, 1d
    Discord webhook                :p0_2, 1d
    Z-Image-Turbo                  :p0_3, 1d
    section 🟡 P1 — Important
    Load tests                     :p1_1, 3d
    LMCache A/B                    :p1_2, 2d
    /v1/models filter              :p1_3, 1d
    Dashboard coût GPU             :p1_4, 3d
    section 🔵 P2 — Améliorations
    Grafana persistence            :p2_1, 1d
    Alerte régression              :p2_2, 2d
    section 🟢 P3 — Nettoyage
    Legacy cleanup                 :p3_1, 2d
    ADR doublon                    :p3_2, 1d
    Documentation                  :p3_3, 1d
```

---

*Document généré suite à l'audit du 2026-07-27. Mis à jour par l'équipe ai-helm.*
