// Vercel serverless function: adds one item to a Nuvio profile's watchlist
// (library) so the "Add to Watchlist" button on the recommendations page
// can write back to Nuvio without ever exposing the account credentials to
// the browser. Mirrors the Nuvio Public API calls in ../../backup_watchlists.py
// (sign in, then RPCs against /rest/v1/rpc/...), plus sync_push_library,
// which the Nuvio app itself only exposes as "replace the whole library" —
// so we pull the current library, upsert the new item, and push it back.

const API_BASE = "https://api.nuvio.tv";

// Nuvio's publishable key is intentionally public (it appears in the
// official API docs); it only identifies the client, all authorization
// comes from the bearer token.
const PUBLISHABLE_KEY =
  process.env.NUVIO_API_KEY || "sb_publishable_1Clq8rlTVACkdcZuqr6_AD__xUUC_EN";

const PAGE_SIZE = 500;

async function nuvioPost(path, body, token) {
  const headers = { "Content-Type": "application/json", apikey: PUBLISHABLE_KEY };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Nuvio API ${path} failed: ${response.status} ${text}`);
  }
  return text ? JSON.parse(text) : null;
}

function signIn(email, password) {
  return nuvioPost("/auth/v1/token?grant_type=password", { email, password }).then(
    (result) => result.access_token
  );
}

function rpc(token, name, payload) {
  return nuvioPost(`/rest/v1/rpc/${name}`, payload, token);
}

async function pullLibrary(token, profileId) {
  const items = [];
  let offset = 0;
  for (;;) {
    const page = await rpc(token, "sync_pull_library", {
      p_profile_id: profileId,
      p_limit: PAGE_SIZE,
      p_offset: offset,
    });
    items.push(...page);
    if (page.length < PAGE_SIZE) return items;
    offset += PAGE_SIZE;
  }
}

function pushLibrary(token, profileId, items) {
  return rpc(token, "sync_push_library", { p_items: items, p_profile_id: profileId });
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  const requiredToken = process.env.ADD_TO_WATCHLIST_TOKEN;
  if (requiredToken && req.headers["x-add-secret"] !== requiredToken) {
    res.status(401).json({ error: "Unauthorized" });
    return;
  }

  const { content_id, content_type, name } = req.body || {};
  if (!content_id || !content_type) {
    res.status(400).json({ error: "content_id and content_type are required" });
    return;
  }

  const email = process.env.NUVIO_EMAIL;
  const password = process.env.NUVIO_PASSWORD;
  if (!email || !password) {
    res.status(500).json({ error: "Server is missing NUVIO_EMAIL / NUVIO_PASSWORD" });
    return;
  }
  const profileId = Number(process.env.NUVIO_PROFILE_INDEX || "1");

  try {
    const token = await signIn(email, password);
    const items = await pullLibrary(token, profileId);
    const alreadyAdded = items.some(
      (item) => item.content_id === content_id && item.content_type === content_type
    );
    if (!alreadyAdded) {
      items.push({ content_id, content_type, name: name || "", added_at: Date.now() });
      await pushLibrary(token, profileId, items);
    }
    res.status(200).json({ ok: true, already_added: alreadyAdded });
  } catch (error) {
    console.error(error);
    res.status(502).json({ error: "Failed to update Nuvio watchlist" });
  }
};
