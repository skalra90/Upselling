import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, Search } from "../../icons/Icons";
import { clock, technique } from "../../lib/format";
import { ChatBubble, ChatGroup } from "./chat";
import { highlight, sideOf } from "./chatUtils";
import { canon, convWho, type RecCtx } from "./shared";

export default function TranscriptTab({
  ctx,
  scrollTo,
  onScrolled,
}: {
  ctx: RecCtx;
  scrollTo: number | null;
  onScrolled: () => void;
}) {
  const { report: r, segments, who } = ctx;
  const convs = r.conversations;
  const [convId, setConvId] = useState("");
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const refs = useRef<Record<number, HTMLDivElement | null>>({});
  const [copied, setCopied] = useState(false);
  const upsellSegs = useMemo(() => {
    const m = new Map<number, string>();
    convs.forEach((c) => c.upsell?.upsell_attempts.forEach((a) => m.set(a.segment_id, a.technique)));
    return m;
  }, [convs]);
  const frustSegs = useMemo(() => {
    const s = new Set<number>();
    convs.forEach((c) => c.mood?.frustration_moments.forEach((m) => s.add(m.segment_id)));
    return s;
  }, [convs]);

  // Exact containment first; only fall back to a small tolerance for float-rounding at a true
  // boundary - otherwise two back-to-back conversations with almost no gap would both match a
  // line right at the seam, and `.find()` would silently attribute it to the earlier one.
  const convOf = (start: number) =>
    convs.find((c) => start >= c.start && start <= c.end) ??
    convs.find((c) => start >= c.start - 0.01 && start <= c.end + 0.01);

  const rows = useMemo(() => {
    let lastConv: number | null = null;
    const list: ({ type: "break"; conv: (typeof convs)[number] } | { type: "line"; seg: (typeof segments)[number] })[] = [];
    for (const s of segments) {
      const conv = convOf(s.start);
      if (convId && String(conv?.conversation_id) !== convId) continue;
      const isUp = upsellSegs.has(s.id);
      const isFr = frustSegs.has(s.id);
      if (kind === "upsell" && !isUp) continue;
      if (kind === "frustrated" && !isFr) continue;
      if (q.trim() && !s.text.toLowerCase().includes(q.trim().toLowerCase())) continue;
      if (!convId && conv && conv.conversation_id !== lastConv) {
        list.push({ type: "break", conv });
        lastConv = conv.conversation_id;
      }
      list.push({ type: "line", seg: s });
    }
    return list;
  }, [segments, convId, kind, q, upsellSegs, frustSegs]); // eslint-disable-line react-hooks/exhaustive-deps

  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const toggleConv = (id: number) =>
    setCollapsed((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  // Group consecutive lines by one speaker; hide the lines of collapsed conversations.
  const blocks = useMemo(() => {
    const out: ({ type: "break"; conv: (typeof convs)[number] } | { type: "group"; segs: (typeof segments)[number][] })[] = [];
    let hidden = false;
    for (const row of rows) {
      if (row.type === "break") {
        out.push(row);
        hidden = collapsed.has(row.conv.conversation_id);
        continue;
      }
      if (hidden) continue;
      const last = out[out.length - 1];
      if (last && last.type === "group" && canon(last.segs[0].speaker) === canon(row.seg.speaker)) last.segs.push(row.seg);
      else out.push({ type: "group", segs: [row.seg] });
    }
    return out;
  }, [rows, collapsed]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (scrollTo == null) return;
    const seg = segments.find((s) => s.id === scrollTo);
    const cid = seg ? convOf(seg.start)?.conversation_id : undefined;
    const wasCollapsed = cid != null && collapsed.has(cid);
    if (wasCollapsed) toggleConv(cid);
    const go = () => {
      const el = refs.current[scrollTo];
      if (el) {
        el.scrollIntoView({ block: "center" });
        el.classList.add("flash");
        setTimeout(() => el.classList.remove("flash"), 1600);
      }
    };
    if (wasCollapsed) setTimeout(go, 60);
    else go();
    onScrolled();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollTo]);

  function transcriptText() {
    let last: number | null = null;
    const out: string[] = [];
    for (const s of segments) {
      const c = convOf(s.start);
      if (c && c.conversation_id !== last) {
        out.push(`\n=== #${c.conversation_id} ${c.topic} ===`);
        last = c.conversation_id;
      }
      out.push(`[${clock(s.start)}] ${s.speaker} (${r.speakers.find((x) => x.speaker === s.speaker)?.role ?? "?"}): ${s.text}`);
    }
    return out.join("\n").trim() + "\n";
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(transcriptText());
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  function download() {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([transcriptText()], { type: "text/plain;charset=utf-8" }));
    a.download = `${r.source_filename.replace(/\.[^.]+$/, "")}-transcript.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  if (segments.length === 0) return <div className="card empty">Transcript not available.</div>;

  return (
    <div className="card">
      <div className="row">
        <select className="sel" style={{ maxWidth: "100%" }} aria-label="Show one conversation" value={convId} onChange={(e) => setConvId(e.target.value)}>
          <option value="">All conversations</option>
          {convs.map((c) => (
            <option key={c.conversation_id} value={c.conversation_id}>
              #{c.conversation_id} {c.topic}
            </option>
          ))}
        </select>
        <select className="sel" aria-label="Show only certain lines" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">All lines</option>
          <option value="upsell">Upsell attempts</option>
          <option value="frustrated">Frustration</option>
        </select>
        <div className="row grow" style={{ position: "relative", minWidth: 180 }}>
          <Search size={15} className="icon-muted" style={{ position: "absolute", left: 11 }} />
          <input
            placeholder="Search words…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ width: "100%", font: "inherit", fontSize: 14, padding: "9px 12px 9px 34px", border: "1px solid var(--line)", borderRadius: 9 }}
          />
        </div>
        <button className="btn ghost" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </button>
        <button className="btn ghost" onClick={download}>
          Download .txt
        </button>
      </div>
      <p className="sub small" style={{ margin: "12px 0 2px" }}>
        {segments.length} lines · {convs.length} conversation{convs.length === 1 ? "" : "s"} · {r.speakers.length} speakers
      </p>
      <p className="sub small" style={{ marginBottom: 10 }}>
        <span className="pill info">Upsell attempt</span> accent edge · <span className="pill bad">Frustration</span> red edge · salesperson on the right
      </p>

      {rows.length === 0 && <p className="sub">No matching lines.</p>}
      <div className="chat">
        {blocks.map((b, i) =>
          b.type === "break" ? (
            <div key={`b${i}`} className="chat-divider">
              <button
                type="button"
                className="chat-divider-btn"
                aria-expanded={!collapsed.has(b.conv.conversation_id)}
                onClick={() => toggleConv(b.conv.conversation_id)}
              >
                <ChevronRight size={14} className="chat-chev" />
                <b>#{b.conv.conversation_id}</b> {b.conv.topic}
                <span className="chat-divider-time">
                  {clock(b.conv.start)}&ndash;{clock(b.conv.end)}
                </span>
              </button>
            </div>
          ) : (
            <ChatGroup key={`g${b.segs[0].id}`} speaker={b.segs[0].speaker} report={r} who={convWho(r, who, convOf(b.segs[0].start)?.conversation_id)}>
              {b.segs.map((s) => {
                const isUp = upsellSegs.has(s.id);
                const isFr = frustSegs.has(s.id);
                return (
                  <ChatBubble
                    key={s.id}
                    side={sideOf(s.speaker, r)}
                    time={clock(s.start)}
                    edge={isUp ? "upsell" : isFr ? "bad" : undefined}
                    tag={isUp ? `Upsell attempt · ${technique(upsellSegs.get(s.id) ?? "")}` : isFr ? "Frustration" : undefined}
                    bubbleRef={(el) => {
                      refs.current[s.id] = el;
                    }}
                  >
                    {highlight(s.text, q)}
                  </ChatBubble>
                );
              })}
            </ChatGroup>
          ),
        )}
      </div>
    </div>
  );
}
