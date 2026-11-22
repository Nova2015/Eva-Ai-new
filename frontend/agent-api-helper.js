const fs = require("fs");
const path = require("path");

function resolveProjectRoot() {
  const configured = process.env.EVA_PROJECT_ROOT?.trim();
  const candidates = [
    configured ? path.resolve(configured) : null,
    path.resolve(__dirname, ".."),
  ].filter(Boolean);

  return candidates.find((root) => fs.existsSync(path.join(root, "src", "app.py"))) || null;
}

function readAgentKey() {
  const root = resolveProjectRoot();
  if (!root) throw new Error("EVA project root not found. Set EVA_PROJECT_ROOT to the repository root.");
  const envPath = path.join(root, ".env");
  if (!fs.existsSync(envPath)) throw new Error(`EVA .env file not found at ${envPath}`);

  const line = fs.readFileSync(envPath, "utf8")
    .split(/\r?\n/)
    .find((item) => /^\s*AGENT_API_KEY\s*=/.test(item));

  const key = line ? line.slice(line.indexOf("=") + 1).trim().replace(/^["']|["']$/g, "") : "";
  if (!key) throw new Error("AGENT_API_KEY is missing");
  return key;
}

async function agentRequest(route, method = "GET", body) {
  const response = await fetch("http://127.0.0.1:8100" + route, {
    method,
    headers: {
      "X-Agent-Key": readAgentKey(),
      ...(body ? { "Content-Type": "application/json" } : {})
    },
    ...(body ? { body: JSON.stringify(body) } : {})
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Agent API error: ${response.status}`);
  return data;
}

module.exports = { agentRequest, resolveProjectRoot };
