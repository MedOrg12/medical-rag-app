const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const read = name => fs.readFileSync(path.join(__dirname, "../static", name), "utf8");

class Element {
  constructor() {
    this.children = []; this.listeners = {}; this.style = {}; this.value = "";
    this.dataset = {}; this.hidden = false; this.scrollHeight = 40; this.innerHTML = "";
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute() {}
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  querySelector() { return this.body ||= new Element(); }
  focus() {}
  scrollIntoView() {}
}

function storage() {
  const data = new Map();
  return { getItem: key => data.get(key) || null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) };
}

function patient(localStorage) {
  const nodes = new Map();
  const document = {
    querySelector(selector) { if (!nodes.has(selector)) nodes.set(selector, new Element()); return nodes.get(selector); },
    querySelectorAll: () => [], createElement: () => new Element(),
  };
  let sequence = 0;
  const context = vm.createContext({ localStorage, document,
    crypto: { randomUUID: () => `new-conversation-${++sequence}` },
    fetch: async () => ({ ok: true, json: async () => ({ ready: true }) }),
  });
  vm.runInContext(read("browser-state.js"), context);
  vm.runInContext(read("patient.js"), context);
  return { context, nodes, evaluate: code => vm.runInContext(code, context) };
}

test("completed conversation, draft and conversation ID survive a new browser context", () => {
  const cache = storage();
  const first = patient(cache);
  first.evaluate(`savedTurns = [{question:'Earlier question', payload:{answer:'Evidence [2].', citations:[{id:2,source:'paper.pdf',excerpt:'Quoted evidence'}]}}]; ui.question.value='Follow-up draft'; saveConversation();`);
  const second = patient(cache);
  assert.equal(second.evaluate("savedTurns.length"), 1);
  assert.equal(second.evaluate("ui.question.value"), "Follow-up draft");
  assert.equal(second.evaluate("conversationId"), first.evaluate("conversationId"));
  assert.equal(second.nodes.get("#messages").children.length, 2);
  assert.equal(second.nodes.get("#messages").hidden, false);
  assert.equal(second.nodes.get("#welcome").hidden, true);
});

test("Start fresh clears cached history and rotates conversation identity", () => {
  const cache = storage();
  const app = patient(cache);
  app.evaluate("ui.question.value='Saved draft'; saveConversation()");
  const oldId = app.evaluate("conversationId");
  app.nodes.get("#new-session").listeners.click[0]();
  assert.notEqual(app.evaluate("conversationId"), oldId);
  assert.equal(cache.getItem("stroke-companion:patient"), null);
  assert.equal(patient(cache).evaluate("ui.question.value"), "");
});

test("an interrupted question returns as a draft without a completed answer", () => {
  const cache = storage();
  patient(cache).evaluate("pendingQuestion='Question still running'; saveConversation()");
  const next = patient(cache);
  assert.equal(next.evaluate("ui.question.value"), "Question still running");
  assert.equal(next.evaluate("savedTurns.length"), 0);
});

test("malformed history and unavailable browser storage do not break the UI", () => {
  const cache = storage();
  cache.setItem("stroke-companion:patient", "invalid json");
  assert.equal(patient(cache).evaluate("savedTurns.length"), 0);
  cache.setItem("stroke-companion:patient", JSON.stringify({version:1,data:{conversationId:'valid-id',turns:[null,{payload:{answer:'bad',citations:[null]}}]}}));
  assert.equal(patient(cache).evaluate("savedTurns.length"), 0);
  const denied = { getItem() { throw Error("denied"); }, setItem() { throw Error("quota exceeded"); }, removeItem() { throw Error("denied"); } };
  assert.equal(patient(denied).evaluate("saveConversation()"), false);
});

test("a completed streamed answer is cached and reuses the persistent conversation ID", async () => {
  const cache = storage();
  const app = patient(cache);
  let submitted;
  app.context.AbortController = AbortController;
  app.context.streamAnswer = async inputs => {
    submitted = inputs;
    return {answer:"Completed answer",citations:[]};
  };
  const conversationId = app.evaluate("conversationId");
  await app.evaluate("ready=true; ask('Follow-up question')");
  assert.equal(submitted.conversation_id, conversationId);
  const restored = patient(cache);
  assert.equal(restored.evaluate("savedTurns[0].payload.answer"), "Completed answer");
  assert.equal(restored.evaluate("conversationId"), conversationId);
});

test("workbench settings and previous result survive a new context", () => {
  const cache = storage();
  function workbench() {
    const nodes = new Map();
    const select = key => { if (!nodes.has(key)) nodes.set(key,new Element()); return nodes.get(key); };
    const state = {answerMode:"patient", query:null};
    const context = vm.createContext({localStorage:cache, $:select, state,
      document:{querySelectorAll:()=>[]}, renderQuery:()=>{},
    });
    vm.runInContext(read("browser-state.js"),context);
    const source = read("dev.js");
    vm.runInContext(source.slice(source.indexOf("function saveWorkbench("),source.indexOf("const icon =")),context);
    return {evaluate:code=>vm.runInContext(code,context),select,state};
  }
  const first = workbench();
  first.select("#question").value = "Draft query";
  first.select("#top-k").value = "8";
  first.select("#screen-provider").value = "gemini";
  first.state.answerMode = "clinician";
  first.state.query = {request:{question:"Earlier query"},response:{answer:"Earlier result",citations:[]}};
  first.evaluate("saveWorkbench()");
  const next = workbench();
  next.evaluate("restoreWorkbench()");
  assert.equal(next.select("#question").value,"Draft query");
  assert.equal(next.select("#top-k").value,8);
  assert.equal(next.state.answerMode,"clinician");
  assert.equal(next.state.query.response.answer,"Earlier result");
});
