export type JobState = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface Job {
  job_id: string;
  status: JobState;
  stage: string;
  progress: number;
  error: string | null;
  filename: string;
  salesperson_name: string | null;
  created_at: string;
  cancel_requested: boolean;
}

export type Sentiment = "positive" | "neutral" | "negative";
export type UpsellResult = "won" | "lost" | "open" | "none" | "unknown";
export type ReplyKind = "accepted" | "rejected" | "undecided" | "no_response";

export interface Pitched {
  salesperson: string;
  segment_id: number;
  item: string;
  technique: string;
  response: ReplyKind;
  quote: string;
  after_rejection: boolean;
}

export interface CallOutcome {
  conversation_id: number;
  topic: string;
  start: number;
  end: number;
  salespeople: string[];
  sentiment: Sentiment;
  sentiment_reasons: string[];
  upsell_result: UpsellResult;
  pitched: Pitched[];
  accepted: number;
  rejected: number;
  products_discussed: string[];
  customer_max_frustration: number | null;
}

export interface ItemStat {
  item: string;
  tried: number;
  accepted: number;
}
export interface SalespersonOutcome {
  speaker: string;
  tried: number;
  accepted: number;
  rejected: number;
  open: number;
  success_rate: number | null;
  items: ItemStat[];
}

export interface Outcomes {
  calls: CallOutcome[];
  positive: number;
  neutral: number;
  negative: number;
  won: number;
  lost: number;
  by_salesperson: SalespersonOutcome[];
}

export type Role = "salesperson" | "customer" | "other";
export type Language = "english" | "hindi" | "hinglish" | "other";
export type Mood = "happy" | "calm" | "neutral" | "confused" | "impatient" | "irritated" | "frustrated" | "angry";
export type Technique =
  | "cross_sell"
  | "upgrade"
  | "bundle"
  | "discount_offer"
  | "warranty_protection"
  | "plan_upgrade"
  | "membership_loyalty"
  | "scarcity_urgency"
  | "social_proof"
  | "other";

export interface UpsellAttempt {
  salesperson: string;
  segment_id: number;
  quote: string;
  technique: Technique;
  offered_item: string;
  salesperson_initiated: boolean;
  after_customer_rejection: boolean;
  handled_objection: boolean;
  customer_response: ReplyKind;
  customer_mood: Mood;
}

export interface UnansweredQuestion {
  segment_id: number;
  speaker: string;
  question: string;
  note: string;
}

export interface UpsellAnalysis {
  customer_requested: string[];
  upsell_attempts: UpsellAttempt[];
  excluded_candidates: string[];
  pushy_upsell: boolean;
  pushy_reason: string;
  confidence: number;
  summary: string;
  greeting_given: boolean;
  greeting_quote: string | null;
  greeting_segment_id: number | null;
  products_discussed: string[];
  customer_feedback: string | null;
  customer_feedback_segment_id: number | null;
  unanswered_questions: UnansweredQuestion[];
  coaching_feedback: string;
}

export interface SpeakerMood {
  speaker: string;
  overall_mood: Mood;
  frustration_level: number;
  trend: "improving" | "stable" | "worsening";
  summary: string;
}

export interface FrustrationMoment {
  segment_id: number;
  speaker: string;
  quote: string;
  evidence_source: "words" | "voice" | "both";
  evidence: string;
}

export interface MoodAnalysis {
  speakers: SpeakerMood[];
  frustration_moments: FrustrationMoment[];
}

export interface Conversation {
  conversation_id: number;
  start: number;
  end: number;
  topic: string;
  language: Language;
  is_sales_interaction: boolean;
  salespeople: string[];
  customers: string[];
  mood: MoodAnalysis | null;
  upsell: UpsellAnalysis | null;
  attempted_upsell: boolean;
  effort_score: number;
  analyzed_by: string | null;
  escalated: boolean;
  budget_note: string | null;
}

export interface SalespersonMetrics {
  speaker: string;
  conversations: number;
  conversations_with_upsell: number;
  upsell_rate: number;
  attempts_total: number;
  attempts_per_conversation: number;
  avg_effort_score: number;
  upsell_talk_time_share: number;
  acceptance_rate: number | null;
  pushy_conversations: number;
  techniques_used: string[];
}

export interface SpeakerSummary {
  speaker: string;
  role: Role;
  title: string | null;
  talk_time_s: number;
}

export interface EvidenceLine {
  segment_id: number;
  speaker: string;
  role: Role;
  start: number;
  end: number;
  text: string;
  is_highlighted: boolean;
}
export type EvidenceKind = "upsell_attempt" | "frustration" | "unanswered_question" | "greeting" | "customer_feedback";
export interface Evidence {
  kind: EvidenceKind;
  conversation_id: number;
  index: number;
  speaker: string;
  segment_id: number;
  quote_found: boolean;
  lines: EvidenceLine[];
}

export interface CallLog {
  step: string;
  provider: string;
  model: string;
  ok: boolean;
  latency_s: number;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  error: string | null;
  fallback_index: number;
}

export interface Report {
  job_id: string;
  source_filename: string;
  duration_s: number;
  transcription_provider: string;
  speakers: SpeakerSummary[];
  has_sales_activity: boolean;
  conversations: Conversation[];
  salespeople: SalespersonMetrics[];
  calls: CallLog[];
  evidence: Evidence[];
  spent_usd: number;
  budget_usd: number | null;
  unpriced_calls: number;
}

export interface Segment {
  id: number;
  speaker: string;
  start: number;
  end: number;
  text: string;
}
export interface TranscriptBody {
  duration: number;
  segments: Segment[];
  chunks: number;
}
/** GET /jobs/{id}/transcript - the transcript plus the raw intermediate role-detection output. */
export interface Transcript {
  transcript: TranscriptBody;
}

/** One day/week/month (or the special "all" bucket) of a salesperson's numbers - every
 * field the backend tracks, since `total` and each entry of `series` share this one shape. */
export interface Bucket {
  /** Conversations where the upsell analysis actually ran (the denominator of the upsell rate). */
  analysed_conversations?: number;
  /** Conversations with 2+ salespeople: conversation-level findings (greeting, pushy, unanswered) are NOT charged to anyone. */
  shared_conversations?: number;
  period: string;
  recordings: number;
  conversations: number;
  conversations_with_upsell: number;
  upsell_rate: number | null;
  attempts: number;
  accepted: number;
  /** Offers the customer clearly accepted or turned down: the base of acceptance_rate. */
  answered_offers?: number;
  acceptance_rate: number | null;
  avg_effort: number | null;
  greeted: number;
  solo_analysed_conversations?: number;
  greeting_rate: number | null;
  unanswered_questions: number;
  pushy_conversations: number;
  avg_customer_frustration: number | null;
  max_customer_frustration?: number | null;
  attempts_per_conversation: number | null;
  re_offers: number;
  objections_handled: number;
  techniques: string[];
  calls_positive: number;
  calls_neutral: number;
  calls_negative: number;
  conversations_won: number;
}
/** One recording a person appears in, with their own stats for that job - the full history,
 * not period-bucketed or capped like `recent_calls`. From GET /people/{name}/recordings. */
export interface RecordingSummary {
  job_id: string;
  filename: string;
  created_at: string;
  stats: Bucket;
}

export interface RecentCall {
  when: string;
  job_id: string;
  filename: string;
  conversation_id: number;
  topic: string;
  sentiment: Sentiment;
  upsell_result: UpsellResult;
  tried: number;
  accepted: number;
}

export type EffortLevel = "high" | "moderate" | "low" | "none";

export interface Person {
  name: string;
  total: Bucket;
  series: Bucket[];
  assessment: {
    rating: "strong" | "solid" | "needs_work";
    headline: string;
    low_sample: boolean;
    /** True when fewer than 3 conversations had this person as the only salesperson; do not show the rating label. */
    insufficient_data?: boolean;
    effort_level: EffortLevel;
    effort_summary: string;
    trend: "improving" | "steady" | "declining" | null;
    strengths: string[];
    improvements: string[];
    /** Optional ideas about upselling, shown after the advice about how they treat customers. */
    upsell_tips?: string[];
  };
  recent_coaching: string[];
  recent_calls: RecentCall[];
  /** False when `total` is the person's latest period but not the CURRENT day/week/month (no calls in the current one). */
  is_current?: boolean;
}

/** How often each selling approach was tried across all recordings, and how often the customer said yes. */
export interface TechniqueStat {
  technique: string;
  attempts: number;
  accepted: number;
  rejected: number;
  /** accepted / (accepted + rejected); null when no offer was clearly answered. */
  acceptance_rate: number | null;
  /** Distinct salespeople who used it. */
  people: number;
}

export interface Dashboard {
  period: "day" | "week" | "month";
  people: Person[];
  /** Label of the current day/week/month for this period, e.g. "2026-10-19". */
  current_period?: string;
  jobs_counted: number;
  jobs_skipped: number;
  unassigned_conversations?: number;
  technique_stats?: TechniqueStat[];
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, init);
  if (r.status === 401) window.dispatchEvent(new Event("auth:session-ended")); // see SESSION_ENDED in auth.tsx
  if (!r.ok) {
    let msg = `Something went wrong (${r.status})`;
    try {
      const body = await r.json();
      if (typeof body.detail === "string") msg = body.detail;
    } catch {
      /* no JSON body */
    }
    throw new Error(msg);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}

export const api = {
  jobs: () => req<Job[]>("/jobs"),
  job: (id: string) => req<Job>(`/jobs/${id}`),
  outcomes: (id: string) => req<Outcomes>(`/jobs/${id}/outcomes`),
  report: (id: string) => req<Report>(`/jobs/${id}/report`),
  transcript: (id: string) => req<Transcript>(`/jobs/${id}/transcript`),
  retry: (id: string) => req<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  cancel: (id: string) => req<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  dashboard: (period: string) => req<Dashboard>(`/dashboard?period=${period}`),
  roster: () => req<{ name: string; recordings: number }[]>("/people/roster"),
  upload: (file: Blob, filename: string, salesperson?: string) => {
    const body = new FormData();
    body.append("file", file, filename);
    if (salesperson?.trim()) body.append("salesperson_name", salesperson.trim());
    return req<Job>("/jobs", { method: "POST", body });
  },
  liveTranscribe: (clip: Blob, filename: string, context: string) => {
    const body = new FormData();
    body.append("file", clip, filename);
    if (context) body.append("context", context);
    return req<{ text: string }>("/live-transcribe", { method: "POST", body });
  },
  personRecordings: (name: string) => req<RecordingSummary[]>(`/people/${encodeURIComponent(name)}/recordings`),
};
