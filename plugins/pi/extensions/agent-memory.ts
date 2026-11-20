// agent-memory for Pi (Stage 3.4).
//
// Maps Pi's extension events to agent-memory adapter events and hands each one to the engine: first to the
// project's session server (started by `amem mcp`, which this extension registers as an MCP server), else to
// `amem hook pi <event>`. All logic lives in the engine (agent_memory/adapters/pi.py); this file only
// translates, queues, and places what comes back. Memory never blocks Pi: every failure is swallowed here,
// and the engine records it as a capture gap.
//
// Environment: AMEM_BIN (where amem is; default amem on PATH, then ~/.local/bin/amem),
// AMEM_PI_MCP=0 (don't register the memory tools).
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { connect } from "node:net";
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { delimiter, join } from "node:path";
import { homedir } from "node:os";
import { randomUUID } from "node:crypto";

const AGENT = "pi";
const TIMEOUT_MS = 120_000;

function findAmem(): string | null {
  if (process.env.AMEM_BIN) return process.env.AMEM_BIN;
  for (const dir of (process.env.PATH || "").split(delimiter)) {
    if (dir && existsSync(join(dir, "amem"))) return join(dir, "amem");
  }
  const local = join(homedir(), ".local", "bin", "amem");
  return existsSync(local) ? local : null;
}

function run(cmd: string, args: string[], input: string, cwd: string): Promise<string | null> {
  return new Promise((resolve) => {
    let out = "";
    let done = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const finish = (value: string | null) => { if (!done) { done = true; clearTimeout(timer); resolve(value); } };
    let child;
    try {
      child = spawn(cmd, args, { cwd, stdio: ["pipe", "pipe", "ignore"] });
    } catch {
      return resolve(null);
    }
    timer = setTimeout(() => { try { child.kill(); } catch {} finish(null); }, TIMEOUT_MS);
    child.on("error", () => finish(null));
    child.stdout.on("data", (d: Buffer) => { out += d; });
    child.on("close", (code: number) => finish(code === 0 ? out : null));
    child.stdin.on("error", () => {});
    child.stdin.end(input);
  });
}

// The session server's protocol (agent_memory/server.py): greeting, header, payload; "OK\n" + output.
function forward(serverFile: string, event: string, body: string): Promise<string | null> {
  let info: { port: number; sid: string; token: string };
  try {
    const [port, sid, token] = readFileSync(serverFile, "utf8").trim().split(/\s+/);
    info = { port: Number(port), sid, token };
  } catch {
    return Promise.resolve(null);
  }
  if (!info.port || !info.sid || !info.token) return Promise.resolve(null);
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    let greeted = false;
    let settled = false;
    const sock = connect({ host: "127.0.0.1", port: info.port });
    const finish = (value: string | null) => { if (!settled) { settled = true; sock.destroy(); resolve(value); } };
    sock.setTimeout(TIMEOUT_MS, () => finish(null));
    sock.on("error", () => finish(null));
    sock.on("data", (d: Buffer) => {
      chunks.push(d);
      if (greeted) return;
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
    });
    sock.on("end", () => {
      const all = Buffer.concat(chunks).toString("utf8");
      finish(greeted && all.startsWith("OK\n") ? all.slice(3) : null);
    });
  });
}

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content.filter((c) => c && c.type === "text").map((c) => c.text).join("\n");
}

export default function agentMemory(pi: ExtensionAPI) {
  const cwd = process.cwd();
  const amem = findAmem();
  if (!amem) {
    console.error("agent-memory: amem not found (set AMEM_BIN, or install it); Pi runs without memory.");
    return;
  }
  const base = ["--project", cwd];

  if (process.env.AMEM_PI_MCP !== "0") {
    // Connects when the session starts (Pi's rule: no processes from the factory). It also runs the session server.
    pi.registerMcpServer("agent-memory", {
      command: amem, args: [...base, "--session", "auto", "mcp"], exposure: "direct",
      description: "Project memory: what happened, what exists, what is known, and what matters now.",
    });
  }

  let serverFile: string | null = null;
  let enabled: Promise<boolean> | null = null;
  const ready = () => (enabled ??= run(amem, [...base, "where"], "", cwd).then((where) => {
    if (where === null) {
      console.error(`agent-memory: ${amem} failed; Pi runs without memory.`);
      return false;
    }
    serverFile = join(where.trim(), "run", "server");
    return true;
  }));

  // One event at a time, in order: an edit's "before" must be recorded before its "after".
  let chain: Promise<unknown> = Promise.resolve();
  const send = (event: string, payload: Record<string, unknown>): Promise<string> => {
    // `delivery` tells a retry (the same body, after a failed hand-off) from a second, identical event: the
    // engine's idempotency keys drop the first and keep the second.
    const body = JSON.stringify({ cwd, delivery: randomUUID(), ...payload });
    const result = chain.then(async () => {
      if (!(await ready())) return "";
      const viaServer = serverFile ? await forward(serverFile, event, body) : null;
      if (viaServer !== null) return viaServer;
      return (await run(amem, [...base, "hook", AGENT, event], body, cwd)) ?? "";
    }).catch(() => "");
    chain = result.then(() => {}, () => {});
    return result;
  };

  const briefs = new Map<string, string>();   // Pi session -> memory section, until a compaction or branch change
  const sid = (ctx: any): string => ctx.sessionManager.getSessionId();

  pi.on("session_start", async (event: any, ctx: any) => {
    briefs.clear();
    const header = ctx.sessionManager.getHeader();
    await send("session", { session_id: sid(ctx), reason: event.reason, parent_session_file: header?.parentSession,
                            session_file: ctx.sessionManager.getSessionFile(), leaf_id: ctx.sessionManager.getLeafId(),
                            model: ctx.model?.id });
  });

  pi.on("before_agent_start", async (event: any, ctx: any) => {
    const id = sid(ctx);
    if (!briefs.has(id)) briefs.set(id, await send("brief", { session_id: id }));
    const brief = briefs.get(id);
    if (brief) event.systemPromptOptions.sections.agent_memory = brief;   // set on every run, or Pi drops it
    if (event.messageType !== "user") return;
    const offers = await send("prompt", { session_id: id, text: event.prompt, leaf_id: ctx.sessionManager.getLeafId() });
    if (offers) return { message: { customType: "agent-memory", content: offers, display: false } };
  });

  pi.on("tool_call", async (event: any, ctx: any) => {
    await send("tool_before", { session_id: sid(ctx), call_id: event.toolCallId, tool: event.toolName,
                                args: event.input, parent_call_id: event.parentToolCallId });
  });

  pi.on("tool_result", async (event: any, ctx: any) => {
    await send("tool_after", { session_id: sid(ctx), call_id: event.toolCallId, tool: event.toolName,
                               args: event.input, content: event.content, is_error: event.isError,
                               structured: event.structuredContent });
  });

  pi.on("message_end", async (event: any, ctx: any) => {
    const m = event.message;
    if (m?.role !== "assistant") return;
    const text = textOf(m.content);
    if (text) await send("text", { session_id: sid(ctx), text, timestamp: m.timestamp, model: m.model,
                                   stop_reason: m.stopReason });
  });

  pi.on("agent_settled", async (_event: any, ctx: any) => { await send("idle", { session_id: sid(ctx) }); });

  pi.on("session_before_compact", async (event: any, ctx: any) => {
    await send("compacting", { session_id: sid(ctx), reason: event.reason });
  });

  pi.on("session_compact", async (event: any, ctx: any) => {
    briefs.delete(sid(ctx));
    await send("compacted", { session_id: sid(ctx), reason: event.reason, summary: event.compactionEntry?.summary });
  });

  pi.on("session_tree", async (event: any, ctx: any) => {
    briefs.delete(sid(ctx));
    await send("tree", { session_id: sid(ctx), new_leaf: event.newLeafId, old_leaf: event.oldLeafId,
                         summary: event.summaryEntry?.summary });
  });

  pi.on("session_shutdown", async (event: any, ctx: any) => {
    await send("shutdown", { session_id: sid(ctx), reason: event.reason });
  });
}
