// Test-only Pi commands, so a scripted run can do what a person does in the TUI:
//   /amem-branch TEXT  go back to before the first user message (/tree) and continue there with TEXT
//   /amem-compact      compact the session now (/compact)
export default function (pi) {
  pi.registerCommand("amem-branch", {
    description: "test: branch from before the first user message",
    handler: async (args, ctx) => {
      const first = ctx.sessionManager.getEntries().find((e) => e.type === "message" && e.message.role === "user");
      await ctx.navigateTree(first.id, { summarize: false });
      pi.sendUserMessage(args || "try another way");
      await new Promise((r) => setTimeout(r, 100));   // let the run start, then wait for it
      await ctx.waitForIdle();
    },
  });
  pi.registerCommand("amem-tools", {
    description: "test: print the registered MCP servers and the memory tools",
    handler: async (_args, ctx) => {
      for (let i = 0; i < 100 && !pi.getAllTools().some((t) => t.name.includes("mem_state")); i++) {
        await new Promise((r) => setTimeout(r, 100));
      }
      const servers = (pi.getMcpServers?.() || []).map((s) => s.name);
      const tools = pi.getAllTools().filter((t) => t.name.includes("mem_")).map((t) => `${t.name}:${t.exposure}`);
      console.log(JSON.stringify({ servers, tools }));
    },
  });
  pi.registerCommand("amem-compact", {
    description: "test: compact now",
    handler: async (_args, ctx) => {
      await new Promise((resolve, reject) => ctx.compact({ onComplete: resolve, onError: reject }));
    },
  });
}
