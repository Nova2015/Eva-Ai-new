const fs = require("fs");

function readAgentKey() {
  const envPath = "D:\\Eva_Ai_brain\\.env";
  if (!fs.existsSync(envPath)) throw new Error("EVA .env file not found");

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

module.exports = { agentRequest };
