/**
 * seed-agents.js — idempotently seed the LibreChat agent fleet (ADR-0088).
 *
 * Runs on the LibreChat image (mongoose + jsonwebtoken + Node fetch are present).
 * Authors agents as the SSO system user (platform@…): find its Mongo _id, mint a
 * LibreChat JWT ({id}, signed with JWT_SECRET — what requireJwtAuth expects),
 * then GET-by-name → PATCH/POST each agent and grant PUBLIC view. Two-phase:
 * leaves first, then orchestrators whose `subagentNames` resolve to agent_ids.
 * Finally prunes platform-authored agents no longer in the fleet (declarative:
 * a rename or removal self-cleans; scoped to this author, never user agents).
 *
 * Env: MONGO_URI, JWT_SECRET, LIBRECHAT_URL, PLATFORM_USER_EMAIL, FLEET_PATH.
 * Fails closed (non-zero exit) on any error — the platform user must have logged
 * in once so its User doc exists.
 */
const mongoose = require('mongoose');
const jwt = require('jsonwebtoken');
const fs = require('fs');

const { MONGO_URI, JWT_SECRET, LIBRECHAT_URL, PLATFORM_USER_EMAIL, FLEET_PATH } = process.env;
const AGENT_VIEWER = 'agent_viewer';

function die(msg) { console.error(`[agent-seed] ${msg}`); process.exit(1); }

// LibreChat's uaParser middleware rejects any non-browser User-Agent with an SSE
// "Illegal request" (NON_BROWSER violation). Node fetch's default UA isn't a
// browser, so present a browser UA on every call.
const BROWSER_UA =
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36';

async function api(method, path, token, body) {
  const res = await fetch(`${LIBRECHAT_URL}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      'User-Agent': BROWSER_UA,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json; try { json = text ? JSON.parse(text) : {}; } catch { json = { raw: text }; }
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status} ${text.slice(0, 300)}`);
  return json;
}

async function main() {
  for (const [k, v] of Object.entries({ MONGO_URI, JWT_SECRET, LIBRECHAT_URL, PLATFORM_USER_EMAIL, FLEET_PATH }))
    if (!v) die(`missing env ${k}`);

  const fleet = JSON.parse(fs.readFileSync(FLEET_PATH, 'utf8'));
  const agents = Array.isArray(fleet) ? fleet : fleet.agents || [];
  if (!agents.length) { console.log('[agent-seed] empty fleet, nothing to do'); return; }

  await mongoose.connect(MONGO_URI); // no db in URI -> default db (LibreChat uses `test`)
  const user = await mongoose.connection.collection('users').findOne({ email: PLATFORM_USER_EMAIL });
  if (!user) die(`platform user ${PLATFORM_USER_EMAIL} not found — log into LibreChat once via SSO first`);
  const token = jwt.sign({ id: user._id.toString() }, JWT_SECRET, { expiresIn: '30m' });
  console.log(`[agent-seed] author=${PLATFORM_USER_EMAIL} (${user._id}) role=${user.role}`);

  // existing agents by name (defensive about the list envelope)
  const listed = await api('GET', '/api/agents?limit=200', token);
  const arr = Array.isArray(listed) ? listed : listed.data || listed.agents || [];
  const idByName = {};
  for (const a of arr) if (a && a.name) idByName[a.name] = a.id;

  async function upsert(spec) {
    const { subagentNames, ...rest } = spec;
    const body = { provider: 'converse', tools: [], ...rest };
    if (subagentNames && subagentNames.length) {
      const agent_ids = subagentNames.map((n) => idByName[n]).filter(Boolean);
      if (agent_ids.length !== subagentNames.length)
        die(`subagents unresolved for ${spec.name}: ${subagentNames.filter((n) => !idByName[n])}`);
      body.subagents = { enabled: true, agent_ids };
    }
    let id = idByName[spec.name];
    if (id) { await api('PATCH', `/api/agents/${id}`, token, body); console.log(`[agent-seed] patched ${spec.name} (${id})`); }
    else { const a = await api('POST', '/api/agents', token, body); id = a.id || (a.agent && a.agent.id); if (!id) die(`create returned no id for ${spec.name}: ${JSON.stringify(a).slice(0,300)}`); idByName[spec.name] = id; console.log(`[agent-seed] created ${spec.name} (${id})`); }
    // grant PUBLIC view (visible to all users) via the generic resource-ACL endpoint
    // PUT /api/permissions/<resourceType>/<resourceId> — `updated`/`removed` are
    // REQUIRED arrays; the top-level public+publicAccessRoleId is expanded to a
    // PUBLIC principal server-side (PermissionsController.updateResourcePermissions).
    // ⚠️ resourceId is the Mongo ObjectId (_id), NOT the public `agent_<nanoid>`
    // id — the ACL layer validates it with mongoose.Types.ObjectId.isValid
    // (PermissionService), so the public id 400s "Invalid resource ID". Resolve
    // _id from Mongo by the public id (we already hold the connection).
    const doc = await mongoose.connection.collection('agents').findOne({ id }, { projection: { _id: 1 } });
    if (!doc) die(`agent doc not found in Mongo for id ${id} (${spec.name})`);
    await api('PUT', `/api/permissions/agent/${doc._id}`, token, { updated: [], removed: [], public: true, publicAccessRoleId: AGENT_VIEWER });
    return id;
  }

  // Phase A: leaves (no subagents), Phase B: orchestrators (resolve names -> ids)
  for (const s of agents.filter((a) => !(a.subagentNames && a.subagentNames.length))) await upsert(s);
  for (const s of agents.filter((a) => a.subagentNames && a.subagentNames.length)) await upsert(s);

  // Prune: delete platform-authored agents no longer in the fleet, so the fleet
  // is DECLARATIVE — a rename (name is the idempotency key, so a rename creates a
  // new agent + orphans the old) or a removal self-cleans on the next seed. Scoped
  // to `author == platform user` so it NEVER touches agents real users created
  // (only the seed authors as this user). Runs after upserts so fleet agents exist.
  const fleetNames = new Set(agents.map((a) => a.name));
  const authored = await mongoose.connection
    .collection('agents')
    .find({ author: user._id })
    .project({ id: 1, name: 1 })
    .toArray();
  for (const a of authored) {
    if (fleetNames.has(a.name)) continue;
    await api('DELETE', `/api/agents/${a.id}`, token);
    console.log(`[agent-seed] pruned ${a.name} (${a.id})`);
  }

  await mongoose.disconnect();
  console.log(`[agent-seed] done: ${Object.keys(idByName).length} agents`);
}

main().catch((e) => die(e.stack || String(e)));
