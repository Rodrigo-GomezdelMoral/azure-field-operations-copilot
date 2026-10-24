import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { type Fault, type Fixture, type Frame, type Persona, type Run, type Step, DEMO, PERSONAS, activeAgent, draft, fold, open, recorded, respond } from "./api";

const EMPTY: Run = { id: "", steps: [], status: "idle", pending: null };
const STATUS: Record<string, string> = {
  idle: "Describe the fault or photograph the component to start.",
  running: "The specialists are working…",
  pending_approval: "Waiting for a supervisor's decision.",
  pending_question: "A specialist needs an answer from the technician.",
  completed: "The run is complete.",
  failed: "The run failed.",
};

function readImage(file: File): Promise<Pick<Fault, "image_base64" | "image_media_type">> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => {
      const url = String(reader.result);
      const media = file.type === "image/png" ? "image/png" : "image/jpeg";
      resolve({ image_base64: url.slice(url.indexOf(",") + 1), image_media_type: media });
    };
    reader.readAsDataURL(file);
  });
}

function TraceStep({ step, active }: { step: Step; active: boolean }) {
  return (
    <li className={`${step.kind} ${active ? "active" : ""}`}>
      <span className={`agent ${step.agent}`}>{step.agent}</span>
      {step.kind === "text" ? (
        <div className="text">{step.text}</div>
      ) : (
        <div className="call">
          {step.text}
          {step.args && step.kind === "call" && <span> {step.args.slice(0, 160)}</span>}
          {(step.result || (step.args && step.args.length > 160)) && (
            <details>
              <summary>{step.result ? "arguments and result" : "arguments"}</summary>
              <pre>{step.args}</pre>
              {step.result && <pre>{step.result}</pre>}
            </details>
          )}
        </div>
      )}
    </li>
  );
}

function Trace({ run, running }: { run: Run; running: boolean }) {
  const active = activeAgent(run);
  return (
    <section>
      <h2>Agent trace · {running ? `${active} is working` : `${run.steps.length} steps`}</h2>
      <ol className="trace">
        {run.steps.map((step, index) => <TraceStep key={index} step={step} active={running && index === run.steps.length - 1} />)}
      </ol>
    </section>
  );
}

/** A card that needs the person's attention scrolls itself into view when it appears. */
function useRevealed() {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => ref.current?.scrollIntoView({ behavior: "smooth", block: "start" }), []);
  return ref;
}

function Approval({ run, persona, busy, onDecide }: { run: Run; persona: Persona; busy: boolean; onDecide: (approved: boolean, reason: string) => void }) {
  const [reason, setReason] = useState("");
  const card = useRevealed();
  const pending = run.pending!;
  return (
    <section className="approval" ref={card}>
      <h2>Approval requested · {pending.agent} wants to run {pending.tool}</h2>
      <pre className="call" style={{ margin: "0 0 8px", whiteSpace: "pre-wrap" }}>{JSON.stringify(pending.arguments, null, 1)}</pre>
      {persona.supervisor ? (
        <>
          <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Reason (kept in the audit trail)" />
          <div className="row" style={{ marginTop: 8 }}>
            <button disabled={busy} onClick={() => onDecide(true, reason)}>Approve</button>
            <button disabled={busy} className="deny" onClick={() => onDecide(false, reason)}>Deny</button>
          </div>
        </>
      ) : (
        <p className="status">Only a supervisor who did not open this intervention can decide. The request survives a restart; the run resumes when it is answered.</p>
      )}
    </section>
  );
}

function Question({ run, busy, onAnswer }: { run: Run; busy: boolean; onAnswer: (answer: string) => void }) {
  const [answer, setAnswer] = useState("");
  const card = useRevealed();
  return (
    <section className="question" ref={card}>
      <h2>{run.pending!.agent} asks the technician</h2>
      <p className="text" style={{ margin: "0 0 8px" }}>{run.pending!.question}</p>
      <form onSubmit={(event) => (event.preventDefault(), onAnswer(answer))}>
        <input value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder="Your answer" />
        <button type="submit" disabled={busy || !answer.trim()}>Answer</button>
      </form>
    </section>
  );
}

function WorkOrder({ run }: { run: Run }) {
  const order = draft(run);
  if (!order) return null;
  const parts = (order.parts as { part_number: string; quantity: number }[] | undefined) ?? [];
  const final = [...run.steps].reverse().find((step) => step.agent === "WorkOrder" && step.kind === "text")?.text;
  return (
    <section className="order">
      <h2>Work order · {final?.match(/WO-[A-Z0-9]+/)?.[0] ?? "draft"}</h2>
      <dl>
        <dt>Asset</dt><dd>{String(order.asset_id)}</dd>
        <dt>Title</dt><dd>{String(order.title)}</dd>
        <dt>Diagnosis</dt><dd>{String(order.diagnosis)}</dd>
        <dt>Procedure</dt><dd>{((order.procedure_refs as string[] | undefined) ?? []).map((ref) => <div key={ref}><code>{ref}</code></div>)}</dd>
        <dt>Parts</dt><dd>{parts.length ? parts.map((line) => `${line.quantity} × ${line.part_number}`).join(", ") : "none"}</dd>
        <dt>Safety</dt><dd>{((order.safety_notes as string[] | undefined) ?? []).join(" · ") || "no safety note"}</dd>
        <dt>Priority</dt><dd>{String(order.priority ?? "normal")}</dd>
      </dl>
    </section>
  );
}

function App() {
  const [persona, setPersona] = useState<Persona>(PERSONAS[0]!);
  const [asset, setAsset] = useState("");
  const [description, setDescription] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [fixture, setFixture] = useState<Fixture | null>(null);
  const [run, setRun] = useState<Run>(EMPTY);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const onFrame = (frame: Frame) => setRun((previous) => fold(previous, frame));

  async function guard(work: (signal: AbortSignal) => Promise<string>) {
    controller.current?.abort();
    controller.current = new AbortController();
    setError("");
    setRunning(true);
    try {
      const id = await work(controller.current.signal);
      setRun((previous) => ({ ...previous, id }));
    } catch (failure) {
      if (!(failure instanceof DOMException && failure.name === "AbortError")) setError(String(failure));
    } finally {
      setRunning(false);
    }
  }

  function start(chosen: Fixture | null, assetId: string, text: string) {
    if (!assetId.trim() || text.trim().length < 10 || running) return;
    setFixture(chosen);
    setRun({ ...EMPTY, status: "running" });
    void guard(async (signal) => {
      const image = photo && !DEMO ? await readImage(photo) : {};
      return open({ asset_id: assetId.trim(), description: text.trim(), ...image }, chosen, persona, onFrame, signal);
    });
  }

  const decide = (decision: { approved?: boolean; reason?: string; answer?: string }) => {
    const pending = run.pending!;
    setRun((previous) => ({ ...previous, status: "running", pending: null }));
    void guard((signal) => respond(run.id, pending, decision, fixture, persona, onFrame, signal));
  };

  return (
    <>
      <header>
        <h1>Field Operations Copilot</h1>
        <p>Four specialists prepare the intervention; no part is reserved and no work order is created without a supervisor's approval.</p>
      </header>
      <main>
        <div className="side">
        {run.pending?.kind === "function_approval" && <Approval run={run} persona={persona} busy={running} onDecide={(approved, reason) => decide({ approved, reason })} />}
        {run.pending?.kind === "user_question" && <Question run={run} busy={running} onAnswer={(answer) => decide({ answer })} />}
        <WorkOrder run={run} />
        <section>
          <h2>Fault report</h2>
          <form onSubmit={(event) => (event.preventDefault(), start(null, asset, description))}>
            <select value={persona.id} onChange={(event) => setPersona(PERSONAS.find((item) => item.id === event.target.value) ?? PERSONAS[0]!)} title="Acting as">
              {PERSONAS.map((item) => <option key={item.id} value={item.id}>Acting as {item.name}</option>)}
            </select>
            <input value={asset} onChange={(event) => setAsset(event.target.value)} placeholder="Asset id, for example P-101" disabled={DEMO} />
            <textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What is wrong, since when, under which load" disabled={DEMO} />
            <label className="photo">
              <input type="file" accept="image/*" capture="environment" style={{ display: "none" }} onChange={(event) => setPhoto(event.target.files?.[0] ?? null)} disabled={DEMO} />
              {photo ? <img src={URL.createObjectURL(photo)} alt="" /> : null}
              <span>{photo ? photo.name : "Photograph the damaged component (optional)"}</span>
            </label>
            <button type="submit" disabled={running || DEMO}>{running ? "Working…" : "Prepare the intervention"}</button>
          </form>
          {DEMO && (
            <>
              <div className="banner" style={{ marginTop: 10 }}>Demo mode: recorded runs are replayed with their real timings halved. No backend is called; approve or deny to see the recorded continuation.</div>
              <div className="chips" style={{ marginTop: 8 }}>
                {recorded.map((item) => <button key={item.title} type="button" disabled={running} onClick={() => (setAsset(item.asset_id), setDescription(item.description), start(item, item.asset_id, item.description))}>{item.title}</button>)}
              </div>
            </>
          )}
          {error && <div className="error" style={{ marginTop: 10 }}>{error}</div>}
          <p className="status" style={{ margin: "10px 0 0" }}><b>{run.status.replace("_", " ")}</b> · {STATUS[run.status] ?? ""}{run.id && run.id !== "demo" ? ` · intervention ${run.id}` : ""}</p>
        </section>
        </div>
        {(run.steps.length > 0 || running) && <Trace run={run} running={running} />}
      </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
