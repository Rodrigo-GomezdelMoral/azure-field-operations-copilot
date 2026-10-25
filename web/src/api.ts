export interface Persona {
  id: string;
  name: string;
  supervisor: boolean;
}
export const PERSONAS: Persona[] = [
  { id: "technician-anna", name: "Anna · technician", supervisor: false },
  { id: "supervisor-marco", name: "Marco · supervisor", supervisor: true },
];
export const DEMO = import.meta.env.VITE_DEMO_MODE === "true";
const AGENTS = ["Triage", "Diagnostic", "Parts", "WorkOrder"];

export interface Pending {
  request_id: string;
  kind: "function_approval" | "user_question";
  agent: string;
  tool: string | null;
  arguments: Record<string, unknown>;
  question: string | null;
}
interface Content {
  type: string;
  text?: string;
  call_id?: string;
  name?: string;
  arguments?: unknown;
  result?: unknown;
}
export interface Frame {
  type: string;
  agent?: string | null;
  data?: { role?: string; author?: string | null; contents?: Content[]; text?: string } | null;
  status?: string;
  pending?: Pending | null;
}
export interface Step {
  agent: string;
  kind: "text" | "call" | "handoff";
  text: string;
  name?: string;
  callId?: string;
  args?: string;
  result?: string;
}
export interface Run {
  id: string;
  steps: Step[];
  status: string;
  pending: Pending | null;
}
interface Segment {
  trigger: "open" | "approve" | "deny" | "answer";
  frames: { at: number; frame: Frame }[];
}
export interface Fixture {
  title: string;
  asset_id: string;
  description: string;
  segments: Segment[];
}

const fixtures = Object.values(import.meta.glob<Fixture>("../fixtures/*.json", { eager: true, import: "default" }));
export const recorded = fixtures;

const asText = (value: unknown): string => (typeof value === "string" ? value : JSON.stringify(value, null, 1) ?? "");
const compact = (text: string): string => text.replace(/\s+/g, " ").trim();
/** The orchestration re-emits an agent's complete message after its streamed chunks; that repeat is not shown twice. */
const repeated = (steps: Step[], agent: string, text: string): boolean =>
  text.length > 80 && steps.some((step) => step.kind === "text" && step.agent === agent && compact(step.text) === compact(text));

const complete = (text: string): boolean => {
  try {
    JSON.parse(text);
    return true;
  } catch {
    return false;
  }
};
/** Tool arguments stream in chunks and are then re-emitted whole under the same call id; the whole copy replaces them. */
const merge = (previous: string, chunk: string): string => (complete(previous) && complete(chunk) ? chunk : previous + chunk);

/** Folds one server-sent frame into the trace: streamed chunks of the same message or tool call are merged. */
export function fold(run: Run, frame: Frame): Run {
  if (frame.type === "status") return { ...run, status: frame.status ?? run.status, pending: frame.pending ?? null };
  if (frame.type !== "output" || !frame.data?.contents) return run;
  const agent = frame.data.author ?? frame.agent ?? "";
  const steps = [...run.steps];
  for (const content of frame.data.contents) {
    const last = steps[steps.length - 1];
    if (content.type === "text" && content.text) {
      if (repeated(steps, agent, content.text)) continue;
      if (last && last.kind === "text" && last.agent === agent) steps[steps.length - 1] = { ...last, text: last.text + content.text };
      else steps.push({ agent, kind: "text", text: content.text });
    } else if (content.type === "function_call" && content.name) {
      const index = steps.findIndex((step) => step.callId === content.call_id);
      const chunk = asText(content.arguments ?? "");
      if (index >= 0) steps[index] = { ...steps[index]!, args: merge(steps[index]!.args ?? "", chunk) };
      else {
        const handoff = content.name.startsWith("handoff_to_");
        const text = handoff ? `→ ${content.name.slice("handoff_to_".length)}` : content.name;
        steps.push({ agent, kind: handoff ? "handoff" : "call", text, name: content.name, callId: content.call_id, args: chunk });
      }
    } else if (content.type === "function_result") {
      const index = steps.findIndex((step) => step.callId === content.call_id);
      if (index >= 0) steps[index] = { ...steps[index]!, result: asText(content.result ?? "") };
    }
  }
  return { ...run, steps };
}

export const activeAgent = (run: Run): string => run.steps[run.steps.length - 1]?.agent ?? AGENTS[0]!;

export function draft(run: Run): Record<string, unknown> | null {
  const call = [...run.steps].reverse().find((step) => step.name === "create_work_order" && step.args);
  try {
    return call ? ((JSON.parse(call.args!) as { draft?: Record<string, unknown> }).draft ?? null) : null;
  } catch {
    return null;
  }
}

async function describe(response: Response): Promise<string> {
  try {
    const problem = (await response.json()) as { detail?: string };
    return `HTTP ${response.status}: ${problem.detail ?? ""}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

async function stream(url: string, body: object, persona: Persona, onFrame: (frame: Frame) => void, signal: AbortSignal): Promise<string> {
  const headers = { "content-type": "application/json", "x-demo-user": persona.id, "x-demo-roles": persona.supervisor ? "supervisor" : "" };
  const response = await fetch(url, { method: "POST", headers, body: JSON.stringify(body), signal });
  if (!response.ok || !response.body) throw new Error(await describe(response));
  const id = response.headers.get("x-intervention-id") ?? url.split("/")[3] ?? "";
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return id;
    buffer += value;
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const raw of frames) {
      const line = raw.split("\n").find((item) => item.startsWith("data: "));
      if (line) onFrame(JSON.parse(line.slice(6)) as Frame);
    }
  }
}

function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => (clearTimeout(timer), reject(new DOMException("aborted", "AbortError"))), { once: true });
  });
}

async function replay(segment: Segment | undefined, onFrame: (frame: Frame) => void, signal: AbortSignal): Promise<void> {
  if (!segment) throw new Error("no recorded run for this step");
  let previous = 0;
  for (const { at, frame } of segment.frames) {
    await pause(Math.min((at - previous) * 0.5, 4000), signal);
    previous = at;
    onFrame(frame);
  }
}

export interface Fault {
  asset_id: string;
  description: string;
  image_base64?: string;
  image_media_type?: "image/jpeg" | "image/png";
}

export function open(fault: Fault, fixture: Fixture | null, persona: Persona, onFrame: (frame: Frame) => void, signal: AbortSignal): Promise<string> {
  if (DEMO) return replay(fixture?.segments.find((segment) => segment.trigger === "open"), onFrame, signal).then(() => "demo");
  return stream("/v1/interventions", fault, persona, onFrame, signal);
}

export function respond(id: string, pending: Pending, decision: { approved?: boolean; reason?: string; answer?: string }, fixture: Fixture | null, persona: Persona, onFrame: (frame: Frame) => void, signal: AbortSignal): Promise<string> {
  if (DEMO) {
    const trigger = decision.answer !== undefined ? "answer" : decision.approved ? "approve" : "deny";
    return replay(fixture?.segments.find((segment) => segment.trigger === trigger), onFrame, signal).then(() => id);
  }
  return stream(`/v1/interventions/${id}/responses`, { request_id: pending.request_id, ...decision }, persona, onFrame, signal);
}
