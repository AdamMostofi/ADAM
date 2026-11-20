// agent-memory for OpenCode (Stage 3.3).
//
// Maps OpenCode's plugin hooks and bus events to agent-memory adapter events and hands each one to the engine:
// first to the project's session server (started by `amem mcp`, which this plugin registers), else to
// `amem hook opencode <event>`. All logic lives in the engine (agent_memory/adapters/opencode.py); this file only
// translates, queues, and places what comes back. Memory never blocks OpenCode: every failure is swallowed here,
// and the engine records it as a capture gap.
//
// Options (opencode.json: "plugin": [["/path/to/plugins/opencode/index.js", { ... }]]):
//   amem:   path to the amem executable (default: $AMEM_BIN, then amem on PATH, then ~/.local/bin/amem)
//   mcp:    false to not register the memory tools (then the plugin runs `amem serve` itself)
import { connect } from "node:net";
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { delimiter, join } from "node:path";
import { homedir } from "node:os";
import { randomUUID } from "node:crypto";

const AGENT = "opencode";
const TIMEOUT_MS = 120_000;

function findAmem(option) {
  if (option) return option;
  if (process.env.AMEM_BIN) return process.env.AMEM_BIN;
  for (const dir of (process.env.PATH || "").split(delimiter)) {
    if (dir && existsSync(join(dir, "amem"))) return join(dir, "amem");
  }
  return join(homedir(), ".local", "bin", "amem");
}

function run(cmd, args, input, cwd) {
  return new Promise((resolve) => {
    let out = "";
    let done = false;
    const finish = (value) => { if (!done) { done = true; clearTimeout(timer); resolve(value); } };
    let child;
    try {
      child = spawn(cmd, args, { cwd, stdio: ["pipe", "pipe", "ignore"] });
    } catch {
      return resolve(null);
    }
    const timer = setTimeout(() => { try { child.kill(); } catch {} finish(null); }, TIMEOUT_MS);
    child.on("error", () => finish(null));
    child.stdout.on("data", (d) => { out += d; });
    child.on("close", (code) => finish(code === 0 ? out : null));
    child.stdin.on("error", () => {});
    child.stdin.end(input);
  });
}

// The session server's protocol (agent_memory/server.py): greeting, header, payload; "OK\n" + output.
function forward(serverFile, event, body) {
  let info;
  try {
    const [port, sid, token] = readFileSync(serverFile, "utf8").trim().split(/\s+/);
    info = { port: Number(port), sid, token };
  } catch {
    return Promise.resolve(null);
  }
  if (!info.port || !info.sid || !info.token) return Promise.resolve(null);
  return new Promise((resolve) => {
    const chunks = [];
    let greeted = false;
    let settled = false;
    const finish = (value) => { if (!settled) { settled = true; sock.destroy(); resolve(value); } };
    const sock = connect({ host: "127.0.0.1", port: info.port });
    sock.setTimeout(TIMEOUT_MS, () => finish(null));
    sock.on("error", () => finish(null));
    sock.on("data", (d) => {
      chunks.push(d);
      if (!greeted) {
        const all = Buffer.concat(chunks);
        const nl = all.indexOf(10);
        if (nl < 0) return;
        if (all.subarray(0, nl).toString().trim() !== `AMEM1 ${info.sid}`) return finish(null);
        greeted = true;
        chunks.length = 0;
        if (nl + 1 < all.length) chunks.push(all.subarray(nl + 1));
        const payload = Buffer.from(body, "utf8");
        sock.write(`AMEM1 ${info.token} ${AGENT} ${event} ${payload.length}\n`);
        sock.write(payload);
      }
    });
    sock.on("end", () => {
      const all = Buffer.concat(chunks).toString("utf8");
      finish(greeted && all.startsWith("OK\n") ? all.slice(3) : null);
    });
  });
}

export const AgentMemory = async (ctx, options = {}) => {
  const directory = ctx.directory || ctx.worktree || process.cwd();
  const amem = findAmem(options.amem);
  const base = ["--project", directory];

  const where = await run(amem, [...base, "where"], "", directory);
  if (where === null) {
    console.error(`agent-memory: ${amem} not found or failed; OpenCode runs without memory.`);
    return {};
  }
  const serverFile = join(where.trim(), "run", "server");

  if (options.mcp === false) {   // no MCP server to host the session server: run one beside OpenCode
    try {
      const child = spawn(amem, [...base, "serve"], { cwd: directory, stdio: ["pipe", "ignore", "ignore"] });
      child.on("error", () => {});
      child.unref?.();
    } catch {}
  }

  // One event at a time, in order: an edit's "before" must be recorded before its "after".
  let chain = Promise.resolve();
  const send = (event, payload) => {
    // `delivery` tells a retry (the same body, after a failed hand-off) from a second, identical event: the
    // engine's idempotency keys drop the first and keep the second.
    const body = JSON.stringify({ directory, delivery: randomUUID(), ...payload });
    const result = chain.then(async () => {
      const viaServer = await forward(serverFile, event, body);
      if (viaServer !== null) return viaServer;
      return (await run(amem, [...base, "hook", AGENT, event], body, directory)) ?? "";
    }).catch(() => "");
    chain = result.then(() => {}, () => {});
    return result;
  };

  const roles = new Map();        // messageID -> "user" | "assistant"
  const briefs = new Map();       // sessionID -> the memory text kept in the system prompt until a compaction
  const sentParts = new Set();    // assistant text parts already sent
  const finishedCalls = new Set(); // tool calls whose result was sent
  let lastId = 0;
  const partId = () => {
    lastId = Math.max(lastId + 1, Date.now());
    return `prt_${lastId.toString(16)}amem${Math.random().toString(36).slice(2, 10)}`;
  };

  return {
    config: async (cfg) => {
      if (options.mcp === false) return;
      cfg.mcp = cfg.mcp || {};
      if (!cfg.mcp["agent-memory"]) {
        cfg.mcp["agent-memory"] = { type: "local", enabled: true,
          command: [amem, ...base, "--session", "auto", "mcp"] };
      }
    },

    event: async ({ event }) => {
      const p = event.properties || {};
      switch (event.type) {
        case "session.created": {
          const s = p.info || {};
          await send("session", { session_id: s.id, parent_id: s.parentID, title: s.title, version: s.version });
          break;
        }
        case "message.updated":
          if (p.info?.id) roles.set(p.info.id, p.info.role);
          break;
        case "message.part.updated": {
          const part = p.part || {};
          if (part.type === "text" && part.time?.end && !part.synthetic && !sentParts.has(part.id)
              && roles.get(part.messageID) === "assistant") {
            sentParts.add(part.id);
            await send("text", { session_id: part.sessionID, message_id: part.messageID, part_id: part.id,
                                 text: part.text });
          } else if (part.type === "tool" && part.state?.status === "error" && !finishedCalls.has(part.callID)) {
            finishedCalls.add(part.callID);
            await send("tool_after", { session_id: part.sessionID, call_id: part.callID, tool: part.tool,
                                       args: part.state.input, error: String(part.state.error ?? "error") });
          }
          break;
        }
        case "session.idle":
          await send("idle", { session_id: p.sessionID });
          break;
        case "session.compacted":
          briefs.delete(p.sessionID);
          await send("compacted", { session_id: p.sessionID });
          break;
        case "session.deleted":
          await send("deleted", { session_id: p.info?.id });
          break;
        // file.edited isn't forwarded: OpenCode publishes it before the edit tool's result, so a reconcile
        // there would record the change as unattributed and the tool's own report as a conflict. The
        // tool result carries the edit with its content ids; changes made outside a tool are found by
        // the reconciles on the next prompt, bash command or idle.
      }
    },

    "chat.message": async (input, output) => {
      const text = (output.parts || []).filter((x) => x.type === "text" && !x.synthetic).map((x) => x.text).join("\n");
      const offers = await send("prompt", { session_id: input.sessionID, message_id: output.message?.id, text,
                                            agent: input.agent, model: input.model?.modelID });
      if (offers && output.message?.id) {
        output.parts.push({ id: partId(), sessionID: input.sessionID, messageID: output.message.id, type: "text",
                            synthetic: true, text: offers });
      }
    },

    "experimental.chat.system.transform": async (input, output) => {
      const sid = input.sessionID;
      if (!sid) return;
      if (!briefs.has(sid)) {
        briefs.set(sid, await send("system", { session_id: sid, model: input.model?.id }));
      }
      const brief = briefs.get(sid);
      if (brief) output.system.push(brief);
    },

    "tool.execute.before": async (input, output) => {
      await send("tool_before", { session_id: input.sessionID, call_id: input.callID, tool: input.tool,
                                  args: output.args });
    },

    "tool.execute.after": async (input, output) => {
      finishedCalls.add(input.callID);
      await send("tool_after", { session_id: input.sessionID, call_id: input.callID, tool: input.tool,
                                 args: input.args, title: output.title, output: output.output,
                                 metadata: output.metadata });
    },

    "experimental.session.compacting": async (input, output) => {
      const keep = await send("compacting", { session_id: input.sessionID });
      if (keep) output.context.push(keep);
    },
  };
};
