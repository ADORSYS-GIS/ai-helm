---
name: security-review
description: A security-focused review procedure for a code change — the threat lenses to apply (injection, authz/IDOR, secrets, SSRF, deserialization, crypto, supply chain), how to grade findings P0–P3, and how to prove a vulnerability before claiming it. Use when reviewing a diff for security, or when a change touches auth, input handling, secrets, network calls, or dependencies.
---

# Security Review

Think like an attacker reviewing THIS change: what can a malicious actor make it
do that the author didn't intend? A security review is not a checklist you skim —
it's an adversarial read of the new attack surface. Pair it with the
`code-review` skill: this one goes deep on the security dimension; that one owns
correctness, tests, and the merge verdict.

## The one rule

> **Prove it, then raise it.** A security finding names the concrete exploit —
> the input, the path it takes, and the sink it reaches — and cites the exact
> lines. An unprovable "this looks unsafe" is a *question* (at most P3), not a
> vulnerability. A false P0 costs more trust than a missed P2.

Be adversarial in *hunting*; be precise in the *claim*. Don't manufacture CVEs to
look thorough, and don't wave a change through because it "isn't a security PR" —
every change is until you've looked.

## Scope: the change, not the repo

Review the new/changed attack surface this diff introduces. A pre-existing flaw
in untouched code is at most one terse "pre-existing, worth a separate fix" note,
never a P0/P1 against this PR. But if the change *reaches into* or *depends on*
that flaw (calls the vulnerable function with new untrusted input), it's in scope.

## Threat lenses — apply every relevant one

For each, trace **untrusted input → dangerous sink** and confirm the path is
reachable in this change:

1. **Injection.** Untrusted data concatenated into an interpreter: SQL/NoSQL,
   shell/`exec`, path (`../` traversal), template (SSTI), LDAP, XPath, header/CRLF,
   log injection. Look for string-built queries/commands instead of
   parameterized/escaped APIs.
2. **AuthN / AuthZ.** New or changed endpoints, routes, RPCs, jobs: is
   authentication required, and is **authorization** checked for *this* user on
   *this* object? IDOR (acting on an id without an ownership/tenant check),
   missing role/scope gate, privilege escalation, auth logic that fails open.
3. **Secrets & credentials.** Hardcoded keys/tokens/passwords, secrets in logs or
   error messages, secrets in URLs/query strings, secrets committed to git or
   baked into images/config. Verify secrets come from the secret store, not code.
4. **SSRF & outbound requests.** A new HTTP/DNS/file call whose URL/host is
   attacker-influenced — can it hit internal metadata endpoints, cloud IMDS, or
   the cluster network? Is there an allowlist?
5. **Deserialization & parsing.** Untrusted input into native deserializers,
   `pickle`/`yaml.load`/`Marshal`, XML (XXE), or zip/tar (zip-slip). Unbounded
   parsing → DoS.
6. **Crypto & randomness.** Weak/again-rolled crypto, ECB, static IV/nonce,
   missing TLS or disabled cert verification, `Math.random()` for tokens,
   predictable ids, timing-unsafe comparisons on secrets.
7. **Sensitive-data exposure.** PII/tokens returned in responses or logs, overly
   broad serializers leaking fields, missing redaction, caching of private data.
8. **Web-specific.** XSS (unescaped output, `dangerouslySetInnerHTML`), CSRF on
   state-changing routes, missing/loosened security headers or CORS `*`, open
   redirect.
9. **Supply chain.** New/updated dependency with a known CVE, an unpinned or
   typosquatted package, a new install script or build step that runs untrusted
   code, a widened image/base.
10. **Resource & DoS.** Unbounded loops/allocations on user input, missing
    rate-limit/quota on an expensive new path, ReDoS (catastrophic regex).

## Severity — grade every finding P0–P3

- **P0 — critical, blocks merge.** A *proven* exploitable flaw: working injection,
  auth bypass / IDOR, secret in code or logs, RCE, SSRF to internal, data
  loss/corruption. If you can describe the exploit, it's P0.
- **P1 — should fix.** A plausible, evidence-backed risk you can't fully prove
  exploitable, or a dependency with a known CVE on a reachable path, or defense
  removed with no compensating control.
- **P2 — medium.** Hardening gaps and weakened-but-not-broken controls: missing
  defense-in-depth, over-broad permissions, a missing security header on a
  non-critical path.
- **P3 — might fix.** Minor hygiene, speculative "what ifs", style-level nits.
  Never blocks.

Calibration: grade on a demonstrated path, not on the presence of a scary
keyword. `eval` on a compile-time constant is not a finding; `eval` on request
data is P0. When you assert a flaw is exploitable, show the input.

## How to report a finding

- **Exploit first:** one sentence of *how* an attacker triggers it (the input +
  the path), then the file:line, then the fix direction.
- **Name the control, not just the bug:** "add an ownership check on `orderId`
  before the update", "parameterize the query", "pull the token from ESO, not the
  ConfigMap".
- **No new surface? Say so explicitly** — "reviewed for injection/authz/secrets;
  this change adds no new attack surface" is a valid, valuable result. But only
  after you've actually applied the lenses.

## Definition of done

- [ ] Every relevant threat lens applied to the new/changed surface.
- [ ] Each finding names a concrete exploit path and cites exact lines.
- [ ] AuthZ verified on every new/changed state-changing entry point.
- [ ] No secret introduced into code, logs, URLs, or images.
- [ ] New dependencies checked for known CVEs and pinned.
- [ ] **No unresolved P0/P1.** Verdict stated with the residual risk, even if "no
      new attack surface".
