// A scripted model for driving the real Pi runtime in tests, with no network and no model.
//
// PI_SCRIPT names a JSON file: a list of steps, one per model request, in order:
//   {"tool": "bash", "args": {"command": "ls"}}   a tool call
//   {"text": "Done."}                              a final answer
// PI_DUMP names a folder: each request's system prompt and messages are written there as request-<n>.json,
// so a test can see exactly what reached the model.
import { createFauxCore, fauxAssistantMessage, fauxText, fauxToolCall } from "@earendil-works/pi-ai";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export default function (pi) {
  const steps = JSON.parse(readFileSync(process.env.PI_SCRIPT, "utf8"));
  const dump = process.env.PI_DUMP;
  if (dump) mkdirSync(dump, { recursive: true });
  let n = 0;
  const step = (s) => (context) => {
    n += 1;
    if (dump) writeFileSync(join(dump, `request-${n}.json`), JSON.stringify(context.messages, null, 1));
    return s.text !== undefined
      ? fauxAssistantMessage(fauxText(s.text))
      : fauxAssistantMessage(fauxToolCall(s.tool, s.args, { id: `call_${n}` }), { stopReason: "toolUse" });
  };
  const core = createFauxCore({ provider: "scripted", models: [{ id: "scripted", contextWindow: 200000, maxTokens: 8192 }] });
  core.setResponses(steps.map(step));
  pi.registerProvider("scripted", {
    name: "Scripted (tests)",
    baseUrl: "http://localhost.invalid",
    apiKey: "none",
    api: core.api,
    models: [{ type: "chat", id: "scripted", name: "scripted", reasoning: false, input: ["text"],
               cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 8192 }],
    streamSimple: core.streamSimple,
  });
}
