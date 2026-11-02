"use strict";

async function streamAnswer(inputs, signal, onText) {
  const response = await fetch("/ask/stream", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(inputs), signal,
  });
  if (!response.ok) throw new Error("The answer request could not be started.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let text = "";
  let result = null;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "error") throw new Error(event.message);
        if (event.type === "delta") { text += event.text; onText(text); }
        if (event.type === "done") result = event.payload;
      }
      if (done) break;
    }
    if (!result) throw new Error("The answer was interrupted. Please try again.");
    return result;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
