# LibreChat S3 Presigned URL Expiry — Problem, Options, and Trade-offs

## Status

**Decision (2026-08-24):** apply the immediate stopgap — max out
`S3_URL_EXPIRY_SECONDS` to `604800` (7 days) — while the long-term fix is
evaluated. See [Decision](#decision) and [Options](#options).

## The problem

LibreChat uses S3 for file storage (`fileStrategy: s3`). Its backend generates
**presigned URLs** for every S3 object and stores that URL as the file's
`filepath`. The frontend renders images/avatars by putting `filepath` directly
into `<img src>`.

The presigned URL default lifetime is **2 minutes**
(`packages/api/src/storage/s3/s3Config.ts` → `DEFAULT_EXPIRY_SECONDS = 2 * 60`).
After that, the URL carries an expired signature and S3 returns `403`, so:

- Uploaded/generated **images** and **avatars** break in the UI shortly after
  upload.
- The image only reappears after a **page refresh** (which regenerates a fresh
  URL).
- **Documents** (PDFs, etc.) are less affected because they are downloads, not
  persistent inline rendering.

This is a **known, maintainer-acknowledged limitation**, not a misconfiguration
on our side.

## Why it happens (root cause)

1. The S3 storage strategy (`packages/api/src/storage/s3/crud.ts`) always calls
   `getSignedUrl(...)` — it returns a signed URL regardless of whether the
   bucket is public or private.
2. The frontend (`client/src/components/Chat/Messages/Content/Part.tsx`,
   `Image.tsx`, `Files.tsx`) uses `filepath` directly in `<img src>`.
3. LibreChat stores the full presigned URL in denormalized snapshots
   (`messages.attachments[]`, `messages.files[]`, `toolcalls.attachments[]`),
   and the URL-refresh logic is only wired into `GET /api/files` and avatar
   dispatchers — **not** the message/toolcall read endpoints. So any
   conversation older than the expiry renders broken tiles.

> **Key subtlety:** even for a **public** bucket, a URL that carries an expired
> `X-Amz-Signature` still returns `403`, because the presence of the signature
> params triggers signature validation. Making the bucket public does **not**
> fix the expiry on its own.

## Evidence / references

- LibreChat docs — [Amazon S3](https://www.librechat.ai/docs/configuration/cdn/s3):
  *"S3 presigned URLs expire for visual assets… Once a URL expires, the image or
  avatar it references will appear broken in the UI until the page is refreshed."*
- [Issue #10145](https://github.com/danny-avila/LibreChat/issues/10145) — "Agent
  images frequently broken when using S3 CDN"
- [Discussion #10280](https://github.com/danny-avila/LibreChat/discussions/10280) —
  maintainer's official response
- [Issue #13751](https://github.com/danny-avila/LibreChat/issues/13751) — presigned
  URLs in `messages.attachments` expire on read
- [Issue #11901](https://github.com/danny-avila/LibreChat/issues/11901) — CloudFront
  strategy work
- [PR #11902](https://github.com/danny-avila/LibreChat/pull/11902) — list-endpoint
  URL refresh fix

## Options

### Option 1 — Max out `S3_URL_EXPIRY_SECONDS` (CURRENT STOPGAP)

Set `S3_URL_EXPIRY_SECONDS: "604800"` (7 days, the AWS ceiling for static IAM
keys).

| | |
|---|---|
| **Pros** | One-line env change; no infra; no replica change; keeps S3 durability |
| **Cons** | Still expires (after 7 days); only works with **static** IAM keys (we use static keys, so OK); does not fix list-endpoint staleness; not "permanent" |
| **Effort** | Trivial |
| **Status** | **Applied** |

### Option 2 — CloudFront / CDN in front of S3 (maintainer-recommended)

Serve images/avatars through a CDN with **stable, permanent URLs** while keeping
the bucket private. LibreChat has a first-class `cloudfront` file strategy.

| | |
|---|---|
| **Pros** | Permanent URLs; edge caching; keeps objects private (signed cookies); maintainer's recommended "proper" fix |
| **Cons** | **AWS-only** (CloudFront) — not available on Hetzner Object Storage; new infrastructure; cost/complexity; Cloudflare R2 alone does NOT fix it (still signs) |
| **Effort** | High (new infra) |
| **Status** | Not applicable to Hetzner without a CDN provider |

### Option 3 — `fileStrategies` (route images/avatars to a persistent store, documents to S3)

Use per-type routing so only persistent visual assets move off S3:

```yaml
fileStrategies:
  avatar:   'local'   # or 'cloudfront' / 'firebase'
  image:    'local'
  document: 's3'
```

| | |
|---|---|
| **Pros** | Surgical — matches "store images locally, keep documents in S3"; maintainer's recommended pattern |
| **Cons** | `local` requires a **single replica** on this cluster (no general RWX storage class); existing S3 files don't migrate; local storage is less durable than S3 |
| **Effort** | Medium (PVC + replica change + config) |
| **Status** | Viable, but blocked by the single-replica constraint |

### Option 4 — Full local storage (`fileStrategy: local`)

Move all file bytes to a local PVC.

| | |
|---|---|
| **Pros** | No expiry at all; simplest mental model; community's most common path |
| **Cons** | **Requires a single replica** (no general RWX storage class on this cluster — only Longhorn on GPU/inference nodes, which is not used for LibreChat); loses HA; less durable than S3; existing S3 files don't migrate |
| **Effort** | Medium |
| **Status** | Rejected for now — we cannot afford to be locked to a single LibreChat replica |

### Option 5 — Public bucket + plain (unsigned) URL

Make the bucket public and patch the backend to return a plain object URL
instead of a presigned one.

| | |
|---|---|
| **Pros** | Permanent URLs; trivial patch |
| **Cons** | **Public** — anyone with the link can view the object (no auth); requires a custom LibreChat image (fork/patch) |
| **Effort** | Medium (custom image) |
| **Status** | Rejected — we want auth-gated access |

### Option 6 — Proxy S3 through LibreChat's API

Serve images via LibreChat's own authenticated endpoint
(`/files/download/:userId/:file_id`, which already streams from S3 with the
`fileAccess` ACL middleware).

| | |
|---|---|
| **Pros** | Permanent, auth-gated URLs; reuses existing endpoint |
| **Cons** | **Explicitly rejected by the maintainer** for server-load reasons (defeats offloading to an image service); requires a custom LibreChat image (frontend must point `<img>` at the proxy endpoint, or backend must return proxy URLs) |
| **Effort** | High (custom image) |
| **Status** | Rejected (maintainer guidance + custom-image cost) |

## Decision

**Adopt Option 1 (max out `S3_URL_EXPIRY_SECONDS` to 7 days) as the immediate
stopgap.** It is a one-line change, keeps S3 durability, and does not lock us to
a single replica.

**Defer** the long-term fix. The leading candidate is **Option 3
(`fileStrategies`)** — route images/avatars to a persistent store and keep
documents on S3 — but it is blocked by the **single-replica** constraint on this
cluster (no general RWX storage class). Revisit if/when:
- a general-purpose RWX storage class is provisioned, or
- a CDN provider compatible with Hetzner Object Storage is adopted (Option 2), or
- we accept the single-replica tradeoff.

## Trade-off summary

| Option | URL lifetime | Auth | Replicas | Infra | Effort | Verdict |
|---|---|---|---|---|---|---|
| 1. Max TTL | 7 days | Private | 2 | none | trivial | **Applied** |
| 2. CDN | Permanent | Private (signed) | 2 | new CDN | high | N/A on Hetzner |
| 3. fileStrategies | Permanent (images) | Private | **1** | PVC | medium | blocked (replicas) |
| 4. Full local | Permanent | Private | **1** | PVC | medium | rejected (replicas) |
| 5. Public bucket | Permanent | Public | 2 | custom image | medium | rejected (auth) |
| 6. Proxy | Permanent | Private | 2 | custom image | high | rejected (load) |

## Related

- Chart: `charts/librechat-app/values.yaml` (`S3_URL_EXPIRY_SECONDS`)
- Ticket: see the GitHub issue this doc resolves
- Upstream: [`danny-avila/LibreChat`](https://github.com/danny-avila/LibreChat),
  [docs.librechat.ai](https://www.librechat.ai)
