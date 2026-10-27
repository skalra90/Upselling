"""Per-salesperson performance, bucketed by day, week or month.

A diarized label ("A", "B") only means something inside one recording, so the same person in two
recordings is linked by a name: assigned in the dashboard (stored in people/names.json), or given
as a hint at upload time when the recording has exactly one salesperson. Anyone without a name
is listed as unassigned instead of being guessed at.

`PersonSummary.total` is the *current* period at the chosen granularity - today's numbers for
"day", this week's for "week", this month's for "month" - not an all-time total, so switching
between them actually changes the headline, the rating and the coaching notes, not just the
trend chart underneath. `series` still covers every period in that person's history, oldest first,
for the chart and for the trend direction in the assessment.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from upsell_poc import jobs
from upsell_poc.analysis.scoring import effort_score
from upsell_poc.outcomes import Sentiment, UpsellResult, call_outcome
from upsell_poc.schemas import ConversationResult, JobReport
from upsell_poc.storage import Storage

log = logging.getLogger(__name__)

Period = Literal["day", "week", "month"]
Rating = Literal["strong", "solid", "needs_work"]
EffortLevel = Literal["high", "moderate", "low", "none"]
Trend = Literal["improving", "steady", "declining"]
NAMES_KEY = "people/names.json"
ROSTER_KEY = "people/roster.json"  # {casefolded name: display name}; the first spelling seen wins
ALIASES_KEY = "people/aliases.json"  # {casefolded name: display name it was merged into}
SAMPLE_LINES = 3


class Bucket(BaseModel):
    period: str  # day: 2026-10-14, week: Monday of the ISO week, month: 2026-10
    recordings: int = 0
    conversations: int = 0
    conversations_with_upsell: int = 0
    upsell_rate: float | None = None
    attempts: int = 0
    accepted: int = 0
    answered_offers: int = 0  # offers the customer clearly accepted or turned down (the base of acceptance_rate)
    acceptance_rate: float | None = None
    avg_effort: float | None = None
    greeted: int = 0
    greeting_rate: float | None = None
    unanswered_questions: int = 0
    pushy_conversations: int = 0
    avg_customer_frustration: float | None = None
    max_customer_frustration: float | None = None  # the worst single conversation in the period
    attempts_per_conversation: float | None = None
    re_offers: int = 0  # offers made again after the customer had already said no
    objections_handled: int = 0
    techniques: list[str] = []
    calls_positive: int = 0
    calls_neutral: int = 0
    calls_negative: int = 0
    conversations_won: int = 0  # conversations where the customer accepted at least one upsell
    # Conversations where the upsell analysis ran: the denominator of upsell_rate and attempts_per_conversation.
    analysed_conversations: int = 0
    # Conversations with 2+ salespeople. Greeting / pushy / unanswered / customer frustration are
    # conversation-level findings, so they are not charged to any one person in these.
    shared_conversations: int = 0
    # Analysed conversations with exactly one salesperson: the denominator of greeting, pushy and unanswered stats.
    solo_analysed_conversations: int = 0


class Assessment(BaseModel):
    rating: Rating
    headline: str
    low_sample: bool
    insufficient_data: bool = False  # too few analysed conversations to rate; the UI should not show the rating
    effort_level: EffortLevel
    effort_summary: str
    trend: Trend | None
    strengths: list[str]
    improvements: list[str]  # about how they treat customers
    upsell_tips: list[str] = []  # optional ideas about upselling, shown last


class RecentCall(BaseModel):
    when: str  # upload time of the recording
    job_id: str
    filename: str
    conversation_id: int
    topic: str
    sentiment: Sentiment
    upsell_result: UpsellResult
    tried: int
    accepted: int


class RecordingSummary(BaseModel):
    """One job a person appears in, with their own stats for that job (not period-bucketed, not capped)."""

    job_id: str
    filename: str
    created_at: str
    stats: Bucket  # same shape as Person.total / each entry of Person.series


class PersonSummary(BaseModel):
    name: str
    total: Bucket
    series: list[Bucket]
    assessment: Assessment
    recent_coaching: list[str]
    recent_calls: list[RecentCall]
    is_current: bool = True  # False: `total` is their latest period, but nothing was recorded in the current one


class SampleLine(BaseModel):
    start: float
    text: str


class Unassigned(BaseModel):
    job_id: str
    speaker: str
    filename: str
    created_at: str
    conversations: int
    title: str | None = None  # role title from role detection, e.g. "Sales associate"
    talk_time_s: float = 0.0
    first_start_s: float | None = None
    sample_lines: list[SampleLine] = []


class RosterEntry(BaseModel):
    name: str
    recordings: int


class TechniqueStat(BaseModel):
    technique: str
    attempts: int
    accepted: int
    rejected: int
    acceptance_rate: float | None  # accepted / (accepted + rejected); None when neither happened
    people: int  # distinct named salespeople who used it


class Dashboard(BaseModel):
    period: Period
    people: list[PersonSummary]
    unassigned: list[Unassigned]
    unassigned_conversations: int = 0
    current_period: str = ""
    jobs_counted: int
    jobs_skipped: int = 0  # completed jobs whose saved report couldn't be read
    technique_stats: list[TechniqueStat] = []  # over all readable recordings, not just the period


def period_label(when: datetime, period: Period) -> str:
    d = when.date()
    if period == "week":
        return (d - timedelta(days=d.weekday())).isoformat()
    if period == "month":
        return f"{d.year:04d}-{d.month:02d}"
    return d.isoformat()


# ------------------------------------------------------------------ identity


def normalise_name(name: str | None) -> str:
    """Trim and collapse internal whitespace: 'Priya   S ' -> 'Priya S'."""
    return " ".join((name or "").split())


def load_names(storage: Storage) -> dict[str, str]:
    return storage.get_json(NAMES_KEY) or {}


class _Identity:
    """Who a typed name really is. Identity is case-insensitive and ignores stray whitespace; the
    first spelling seen wins (the stored roster first, then older assignments, then upload hints),
    and merges (aliases) are followed, so 'rahul', 'Rahul ' and a merged 'Rahul K' all become one
    person. This is the single place names are resolved - dashboard, recordings and roster all use it.
    """

    def __init__(self, roster: dict[str, str], aliases: dict[str, str], names: dict[str, str]) -> None:
        self.names = names  # raw "job_id:speaker" -> name, exactly as stored
        self.aliases = {k: v for k, v in aliases.items() if isinstance(v, str)}
        self.display: dict[str, str] = {}
        for shown in roster.values():
            if isinstance(shown, str) and normalise_name(shown):
                self.display.setdefault(normalise_name(shown).casefold(), normalise_name(shown))
        for stored in names.values():
            self.canon(stored)

    @classmethod
    def load(cls, storage: Storage, statuses: list[jobs.JobStatus] | None = None) -> _Identity:
        identity = cls(storage.get_json(ROSTER_KEY) or {}, storage.get_json(ALIASES_KEY) or {}, load_names(storage))
        for status in sorted(statuses or [], key=lambda s: s.created_at):
            identity.canon(status.salesperson_name)
        return identity

    def _chase(self, name: str | None) -> str:
        """The name after following merges (cycle-safe)."""
        current = normalise_name(name)
        seen: set[str] = set()
        while current and (slug := current.casefold()) in self.aliases and slug not in seen:
            seen.add(slug)
            current = normalise_name(self.aliases[slug])
        return current

    def canon(self, name: str | None) -> str:
        """The display name this belongs to, registering it as the spelling if it is new. '' if empty."""
        target = self._chase(name)
        if not target:
            return ""
        return self.display.setdefault(target.casefold(), target)

    def known(self, name: str | None) -> bool:
        target = self._chase(name)
        return bool(target) and target.casefold() in self.display

    def resolve(self, status: jobs.JobStatus, sales_people: list[str], sp: str) -> str | None:
        """Who a diarized label ("A", "B") really is, in one job: an explicit assignment first, then
        the upload-time hint but only when it's unambiguous (exactly one salesperson in the job).
        """
        name = self.canon(self.names.get(f"{status.job_id}:{sp}"))
        if not name and len(sales_people) == 1:
            name = self.canon(status.salesperson_name)
        return name or None

    def save_roster(self, storage: Storage) -> None:
        storage.put_json(ROSTER_KEY, self.display)


def register_name(storage: Storage, name: str | None) -> str | None:
    """Canonical display name for a typed name (an upload hint, say), remembered in the roster."""
    identity = _Identity.load(storage)
    shown = identity.canon(name)
    if shown:
        identity.save_roster(storage)
    return shown or None


def set_name(storage: Storage, job_id: str, speaker: str, name: str) -> None:
    identity = _Identity.load(storage)
    names = identity.names
    key = f"{job_id}:{speaker}"
    shown = identity.canon(name)
    if shown:
        names[key] = shown
        identity.save_roster(storage)
    else:
        names.pop(key, None)
    storage.put_json(NAMES_KEY, names)


def merge_people(storage: Storage, from_name: str, into_name: str) -> None:
    """Make `from_name` another spelling/duplicate of `into_name`. ValueError if either is empty,
    KeyError if either is not a known person. Merging a person into themselves does nothing."""
    if not normalise_name(from_name) or not normalise_name(into_name):
        raise ValueError("both names are required")
    identity = _Identity.load(storage, _all_statuses(storage))
    for n in (from_name, into_name):
        if not identity.known(n):
            raise KeyError(normalise_name(n))
    source, target = identity.canon(from_name), identity.canon(into_name)
    if source.casefold() == target.casefold():
        return
    identity.aliases[source.casefold()] = target
    storage.put_json(ALIASES_KEY, identity.aliases)
    identity.save_roster(storage)


# ------------------------------------------------------------------ metrics


class _Acc:
    def __init__(self) -> None:
        self.recordings: set[str] = set()
        self.convs = 0
        self.analysed = 0
        self.shared = 0
        self.solo_analysed = 0
        self.with_upsell = 0
        self.attempts = 0
        self.accepted = 0
        self.decided = 0
        self.efforts: list[float] = []
        self.greeted = 0
        self.unanswered = 0
        self.pushy = 0
        self.frustration: list[float] = []
        self.re_offers = 0
        self.objections = 0
        self.techniques: set[str] = set()
        self.sentiment = {"positive": 0, "neutral": 0, "negative": 0}
        self.won = 0

    def add(self, job_id: str, conv: ConversationResult, person: str) -> None:
        self.recordings.add(job_id)
        self.convs += 1
        # Greeting, pushiness, unanswered questions and customer frustration describe the whole
        # conversation, not one salesperson: with two salespeople we can't say whose they are.
        shared = len(set(conv.salespeople)) > 1
        self.shared += shared
        u = conv.upsell
        if u:
            self.analysed += 1
            mine = [a for a in u.upsell_attempts if a.salesperson == person]
            self.attempts += len(mine)
            self.with_upsell += bool(mine)
            decided = [a for a in mine if a.customer_response in ("accepted", "rejected")]
            self.decided += len(decided)
            self.accepted += sum(a.customer_response == "accepted" for a in decided)
            self.efforts.append(effort_score(u, person))
            self.re_offers += sum(a.after_customer_rejection for a in mine)
            self.objections += sum(a.handled_objection for a in mine)
            self.techniques |= {a.technique for a in mine}
            if not shared:
                self.solo_analysed += 1
                self.greeted += bool(u.greeting_given)
                self.unanswered += len(u.unanswered_questions)
                self.pushy += bool(u.pushy_upsell)
        outcome = call_outcome(conv)
        self.sentiment[outcome.sentiment] += 1
        self.won += any(p.response == "accepted" and p.salesperson == person for p in outcome.pitched)
        if conv.mood and not shared:
            self.frustration += [m.frustration_level for m in conv.mood.speakers if m.speaker in conv.customers]

    def bucket(self, label: str) -> Bucket:
        def ratio(n: int, d: int) -> float | None:
            return round(n / d, 3) if d else None

        def mean(xs: list[float]) -> float | None:
            return round(sum(xs) / len(xs), 1) if xs else None

        return Bucket(
            period=label,
            recordings=len(self.recordings),
            conversations=self.convs,
            conversations_with_upsell=self.with_upsell,
            upsell_rate=ratio(self.with_upsell, self.analysed),
            attempts=self.attempts,
            accepted=self.accepted,
            answered_offers=self.decided,
            acceptance_rate=ratio(self.accepted, self.decided),
            avg_effort=mean(self.efforts),
            greeted=self.greeted,
            greeting_rate=ratio(self.greeted, self.solo_analysed),
            unanswered_questions=self.unanswered,
            pushy_conversations=self.pushy,
            avg_customer_frustration=mean(self.frustration),
            max_customer_frustration=max(self.frustration) if self.frustration else None,
            attempts_per_conversation=round(self.attempts / self.analysed, 2) if self.analysed else None,
            re_offers=self.re_offers,
            objections_handled=self.objections,
            techniques=sorted(self.techniques),
            calls_positive=self.sentiment["positive"],
            calls_neutral=self.sentiment["neutral"],
            calls_negative=self.sentiment["negative"],
            conversations_won=self.won,
            analysed_conversations=self.analysed,
            shared_conversations=self.shared,
            solo_analysed_conversations=self.solo_analysed,
        )


# Below this, say so rather than judge someone on a couple of calls. It counts conversations where the person was the
# only salesperson: those are the ones greeting, listening, pressure and mood are measured on, so they are what a
# rating stands on. Conversations shared with a colleague do not count toward it.
MIN_CONVERSATIONS = 3
MIN_ANSWERED_OFFERS = 3  # "customers say yes" is only judged once this many offers got a clear answer
SEVERE_FRUSTRATION = 7  # one customer this frustrated keeps the rating from being "Excelling"


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{round(v * 100)}%"


TREND_MARGIN = 0.10  # a signal "moved" by 10 percentage points, 0.1 unanswered questions per conversation, or 1 point of frustration


def _customer_trend(series: list[Bucket]) -> Trend | None:
    """Direction of how the salesperson treats customers - never of upselling or of effort.

    Compares the latest period with >= MIN_CONVERSATIONS analysed conversations against the closest earlier
    period that also has that many; fewer than two such periods -> None. Signals compared: greeting rate
    (higher is better), customer questions left unanswered per conversation (lower), pushy share of solo
    conversations (lower) and average customer frustration (lower, 1 point = 10 points).
    'improving' when at least two signals got better by the margin and none got worse by it; 'declining' is
    the mirror image; anything else (mixed, or small moves) is 'steady'. How often someone upsells, or how
    often customers say yes to an offer, does not move the arrow.
    """
    enough = [b for b in series if b.solo_analysed_conversations >= MIN_CONVERSATIONS]
    if len(enough) < 2:
        return None
    prev, cur = enough[-2], enough[-1]

    def pushy(b: Bucket) -> float | None:
        return b.pushy_conversations / b.solo_analysed_conversations if b.solo_analysed_conversations else None

    def unanswered(b: Bucket) -> float | None:
        return b.unanswered_questions / b.solo_analysed_conversations if b.solo_analysed_conversations else None

    moves: list[float] = []  # positive = better
    for a, b, higher_is_better, scale in (
        (prev.greeting_rate, cur.greeting_rate, True, 1.0),
        (unanswered(prev), unanswered(cur), False, 1.0),
        (pushy(prev), pushy(cur), False, 1.0),
        (prev.avg_customer_frustration, cur.avg_customer_frustration, False, 10.0),
    ):
        if a is None or b is None:
            continue
        diff = (b - a) / scale
        moves.append(diff if higher_is_better else -diff)
    better = sum(m >= TREND_MARGIN - 1e-9 for m in moves)
    worse = sum(m <= -TREND_MARGIN + 1e-9 for m in moves)
    if better >= 2 and worse == 0:
        return "improving"
    if worse >= 2 and better == 0:
        return "declining"
    return "steady"


# How much each category counts towards the rating. How a salesperson treats customers (greeting, listening, mood,
# pressure) counts for more than upselling itself, which is two of the six categories.
W_GREETING, W_LISTENING, W_MOOD, W_PUSHY = 3, 3, 3, 2
W_UPSELL_REACH, W_CONVERSION = 2, 2


def assess(t: Bucket, series: list[Bucket]) -> Assessment:
    """Plain, explainable rules over the totals - no model call. Every line cites the number behind it.

    Points are only awarded for categories that have data; the rating is points over the points
    that were available (>= 75% strong, >= 50% solid), so missing analysis never helps or hurts.
    """
    n = t.analysed_conversations
    d = t.solo_analysed_conversations  # denominator for conversation-level findings
    # How they treat customers comes first in the advice; upselling is listed last, as optional tips.
    handling_good: list[str] = []
    sales_good: list[str] = []
    improvements: list[str] = []  # things to fix about how they treat customers
    upsell_tips: list[str] = []
    points = 0.0
    available = 0.0
    pushy_share = t.pushy_conversations / d if d else 0.0
    unanswered_per = t.unanswered_questions / d if d else 0.0

    if d:
        # listening
        available += W_LISTENING
        if unanswered_per <= 0.1:
            points += W_LISTENING
            handling_good.append("Answers what customers ask.")
        elif unanswered_per <= 0.3:
            points += W_LISTENING / 2
            improvements.append(
                f"{t.unanswered_questions} customer question{'s' if t.unanswered_questions != 1 else ''} went unanswered - answer every question before anything else."
            )
        else:
            improvements.append(
                f"{t.unanswered_questions} customer question{'s' if t.unanswered_questions != 1 else ''} went unanswered across {d} conversation{'s' if d != 1 else ''} - answer every question before anything else."
            )
        # pushiness
        available += W_PUSHY
        if pushy_share <= 0.1:
            points += W_PUSHY
            if t.attempts:
                handling_good.append("Accepts a 'no' without pressuring the customer.")
        elif pushy_share <= 0.3:
            points += W_PUSHY / 2
            improvements.append(
                f"Kept pitching after a clear 'no' in {t.pushy_conversations} of {d} conversations - when a customer declines, accept it and move on."
            )
        else:
            improvements.append(
                f"Kept pitching after a clear 'no' in {t.pushy_conversations} of {d} conversations - when a customer declines, accept it and move on."
            )
    # customer mood
    if t.avg_customer_frustration is not None:
        available += W_MOOD
        avg = t.avg_customer_frustration
        if avg < 3:
            points += W_MOOD
            handling_good.append(f"Most customers stay calm (average {avg}/10).")
        elif avg < 5:
            points += W_MOOD / 2
            improvements.append(
                f"Customers get somewhat tense (average {avg}/10) - slow down and acknowledge their concerns."
            )
        else:
            improvements.append(
                f"Customers leave frustrated (average {avg}/10) - go through the flagged conversations together."
            )
        worst = t.max_customer_frustration
        if worst is not None and worst >= 5 and avg < 5:
            how = "very frustrated" if worst >= 7 else "clearly irritated"
            improvements.append(
                f"A customer got {how} (worst conversation {worst:g}/10) - go through that conversation together."
            )
    # greeting
    if t.greeting_rate is not None:
        available += W_GREETING
        if t.greeting_rate >= 0.8:
            points += W_GREETING
            handling_good.insert(0, f"Greets customers consistently ({_pct(t.greeting_rate)} of conversations).")
        elif t.greeting_rate >= 0.5:
            points += W_GREETING / 2
            improvements.append(
                f"Greet every customer - only {_pct(t.greeting_rate)} of conversations started with a greeting."
            )
        else:
            improvements.append(f"Start each conversation with a greeting - only {_pct(t.greeting_rate)} had one.")
    if t.objections_handled:
        handling_good.append(
            f"Answered customer objections while offering ({t.objections_handled} time{'s' if t.objections_handled != 1 else ''})."
        )
    # upselling: counts towards the rating, but the advice about it comes last and is optional
    if t.upsell_rate is not None:
        available += W_UPSELL_REACH
        if t.upsell_rate >= 0.6:
            points += W_UPSELL_REACH
            sales_good.append(f"Looks for add-on sales in most conversations ({_pct(t.upsell_rate)}).")
        elif t.upsell_rate >= 0.3:
            points += W_UPSELL_REACH / 2
            upsell_tips.append(
                f"Tries an upsell in {_pct(t.upsell_rate)} of conversations - offer something relevant once the customer's own request is handled."
            )
        else:
            upsell_tips.append(
                f"Rarely offers an add-on ({_pct(t.upsell_rate)} of conversations) - suggest something relevant once the customer's own request is handled."
            )
    # conversion (no answered offers = nothing to judge, not a free point)
    if t.acceptance_rate is not None and t.answered_offers >= MIN_ANSWERED_OFFERS:
        available += W_CONVERSION
        if t.acceptance_rate >= 0.4:
            points += W_CONVERSION
            sales_good.append(f"Customers accept {_pct(t.acceptance_rate)} of the offers that get an answer.")
        elif t.acceptance_rate >= 0.2:
            points += W_CONVERSION / 2
        elif t.attempts >= 3:
            upsell_tips.append(
                f"Only {_pct(t.acceptance_rate)} of offers are accepted - tie the add-on to what the customer just asked for."
            )
    if t.attempts >= 3 and len(t.techniques) <= 1:
        upsell_tips.append("Uses a single sales technique - mix in bundles, upgrades or protection plans.")
    strengths = handling_good + sales_good

    low_sample = d < MIN_CONVERSATIONS
    insufficient = low_sample or available == 0
    rating: Rating
    if available == 0:
        rating = "solid"  # nothing to judge; insufficient_data is what tells the reader so
    else:
        rating = "strong" if points * 4 >= available * 3 else "solid" if points * 2 >= available else "needs_work"
        worst_seen = t.max_customer_frustration
        if rating == "strong" and worst_seen is not None and worst_seen >= SEVERE_FRUSTRATION:
            rating = "solid"  # an average can hide one customer who left very upset
    if insufficient and n == 0:
        headline = f"Not enough analysed data to rate this person yet (0 of {MIN_CONVERSATIONS} conversations analysed)."
    elif insufficient:
        headline = (
            f"Not enough conversations to rate this person yet ({d} of {MIN_CONVERSATIONS} where they were the only "
            f"salesperson)."
        )
    else:
        headline = {
            "strong": "Excelling across the board",
            "solid": "On track, with a few things to tighten up",
            "needs_work": "Several areas where they could use support",
        }[rating]

    # effort: how actively and persistently they sell
    efforts = t.avg_effort
    level: EffortLevel
    if n == 0:
        level, summary = "none", "No analysed conversations, so selling effort can't be measured."
    elif t.attempts == 0 or efforts is None:
        level, summary = (
            "none",
            f"No upsell attempts in {n} analysed conversation{'s' if n != 1 else ''} - little selling effort beyond what customers asked for.",
        )
    else:
        level = "high" if efforts >= 4.5 else "moderate" if efforts >= 2.5 else "low"
        bits = [
            f"effort score {efforts}/10",
            f"{t.attempts_per_conversation} offers per conversation",
            f"{len(t.techniques)} technique{'s' if len(t.techniques) != 1 else ''}",
        ]
        if t.re_offers:
            bits.append(f"kept trying after a 'no' {t.re_offers} time{'s' if t.re_offers != 1 else ''}")
        if t.objections_handled:
            bits.append(f"handled {t.objections_handled} objection{'s' if t.objections_handled != 1 else ''}")
        label = {
            "high": "Working hard at selling",
            "moderate": "Putting in a moderate effort",
            "low": "Low effort so far",
        }[level]
        summary = f"{label}: " + ", ".join(bits) + "."
    trend = _customer_trend(series)
    if low_sample:
        if d:
            improvements.append(
                f"Only {d} conversation{'s' if d != 1 else ''} with a single salesperson so far - treat this as a first impression."
            )
        elif n:
            improvements.append("Every analysed conversation so far was shared with a colleague, so customer handling can't be judged yet.")
        else:
            improvements.append(f"None of the {t.conversations} conversation(s) could be analysed yet.")
    return Assessment(
        rating=rating,
        headline=headline,
        low_sample=low_sample,
        insufficient_data=insufficient,
        effort_level=level,
        effort_summary=summary,
        trend=trend,
        strengths=strengths,
        improvements=improvements,
        upsell_tips=upsell_tips,
    )


def _all_statuses(storage: Storage) -> list[jobs.JobStatus]:
    return jobs.list_statuses(storage, limit=10_000)


def _completed_reports(storage: Storage) -> Iterator[tuple[jobs.JobStatus, dict]]:
    """Every completed job that has a saved report, oldest-storage-order - the traversal shared
    by build_dashboard and build_person_recordings. Each caller still calls `jobs.parse_report`
    itself and handles a failure differently (build_dashboard counts and logs it as skipped;
    build_person_recordings just ignores that one recording), so this only factors out the
    "find completed jobs with a saved report" part, not the parsing.

    Both callers still do their own full O(n) scan+parse over every completed job - for this
    POC's actual scale (a handful of recordings) that's milliseconds twice over, not worth a
    cache. If this ever runs against thousands of real recordings, memoize by job_id here
    instead of duplicating that fix in each caller.
    """
    for status in _all_statuses(storage):
        if status.status != "completed":
            continue
        raw = storage.get_json(jobs.report_key(status.job_id))
        if not raw:
            continue
        yield status, raw


def _iter_person_labels(
    report: JobReport, status: jobs.JobStatus, identity: _Identity
) -> Iterator[tuple[ConversationResult, str, str | None]]:
    """Every sales conversation in one parsed report, crossed with every salesperson label in it:
    yields (conversation, label, resolved_name_or_None). The conversation/label walk shared by
    build_dashboard, build_person_recordings and build_roster, so they can't drift apart on *which*
    conversations and labels count - only on what each caller does with the result.
    """
    sales_people = sorted({sp for c in report.conversations if c.is_sales_interaction for sp in c.salespeople})
    for c in report.conversations:
        if not c.is_sales_interaction:
            continue
        for sp in c.salespeople:
            yield c, sp, identity.resolve(status, sales_people, sp)


def _speaker_lines(storage: Storage, job_id: str) -> dict[str, list[tuple[float, str]]]:
    """speaker -> [(start, text)] from the job's stored transcript; {} if it is missing or unreadable."""
    try:
        raw = storage.get_json(jobs.transcript_key(job_id))
        doc = raw.get("transcript", raw) if isinstance(raw, dict) else {}
        out: dict[str, list[tuple[float, str]]] = {}
        for seg in doc.get("segments") or []:
            speaker, start = seg.get("speaker"), seg.get("start")
            if isinstance(speaker, str) and isinstance(start, int | float):
                out.setdefault(speaker, []).append((float(start), str(seg.get("text") or "").strip()))
        return {k: sorted(v) for k, v in out.items()}
    except Exception:  # noqa: BLE001 - a bad transcript must never break the dashboard
        log.warning("dashboard: couldn't read transcript for job %s", job_id)
        return {}


def build_dashboard(storage: Storage, period: Period = "day", now: datetime | None = None) -> Dashboard:
    identity = _Identity.load(storage, _all_statuses(storage))
    current = period_label(now or datetime.now(UTC), period)
    per_person: dict[str, dict[str, _Acc]] = defaultdict(lambda: defaultdict(_Acc))
    # Flat per-name (not per-period-bucket): "recent" means the person's actual most recent
    # activity regardless of which Daily/Weekly/Monthly tab is selected. Scoping these to only
    # the latest bucket used to make Daily view show almost nothing for anyone who hadn't
    # recorded a call literally today, even with plenty of calls earlier that same week.
    coaching: dict[str, list[tuple[str, str]]] = defaultdict(list)
    calls: dict[str, list[RecentCall]] = defaultdict(list)
    unassigned: dict[tuple[str, str], Unassigned] = {}
    tech_acc: dict[str, list[int]] = {}  # technique -> [attempts, accepted, rejected], all periods
    tech_people: dict[str, set[str]] = {}
    counted = 0
    skipped = 0

    for status, raw in _completed_reports(storage):
        report = jobs.parse_report(raw)
        if report is None:
            log.warning("dashboard: skipping unreadable report for job %s", status.job_id)
            skipped += 1
            continue
        counted += 1
        when = datetime.fromisoformat(status.created_at)
        label = period_label(when, period)
        lines: dict[str, list[tuple[float, str]]] | None = None  # read the transcript at most once per job
        for c, sp, name in _iter_person_labels(report, status, identity):
            if not name:
                key = (status.job_id, sp)
                entry = unassigned.get(key)
                if entry is None:
                    if lines is None:
                        lines = _speaker_lines(storage, status.job_id)
                    info = next((s for s in report.speakers if s.speaker == sp), None)
                    spoken = lines.get(sp, [])
                    entry = unassigned[key] = Unassigned(
                        job_id=status.job_id,
                        speaker=sp,
                        filename=status.filename,
                        created_at=status.created_at,
                        conversations=0,
                        title=info.title if info else None,
                        talk_time_s=info.talk_time_s if info else 0.0,
                        first_start_s=spoken[0][0] if spoken else None,
                        sample_lines=[SampleLine(start=t, text=x[:140]) for t, x in spoken if x][:SAMPLE_LINES],
                    )
                entry.conversations += 1
                continue
            per_person[name][label].add(status.job_id, c, sp)
            for a in c.upsell.upsell_attempts if c.upsell else []:
                if a.salesperson != sp:
                    continue
                tech = tech_acc.setdefault(a.technique, [0, 0, 0])
                tech[0] += 1
                tech[1] += a.customer_response == "accepted"
                tech[2] += a.customer_response == "rejected"
                tech_people.setdefault(a.technique, set()).add(name)
            o = call_outcome(c)
            mine = [p for p in o.pitched if p.salesperson == sp]
            calls[name].append(
                RecentCall(
                    when=status.created_at,
                    job_id=status.job_id,
                    filename=status.filename,
                    conversation_id=c.conversation_id,
                    topic=c.topic,
                    sentiment=o.sentiment,
                    upsell_result="won" if any(p.response == "accepted" for p in mine) else o.upsell_result,
                    tried=len(mine),
                    accepted=sum(p.response == "accepted" for p in mine),
                )
            )
            if c.upsell and c.upsell.coaching_feedback:
                coaching[name].append((status.created_at, c.upsell.coaching_feedback))

    people = []
    for name, buckets in per_person.items():
        series = [buckets[lbl].bucket(lbl) for lbl in sorted(buckets)]
        total = series[-1]  # the person's latest period at this granularity (see is_current)
        people.append(
            PersonSummary(
                name=name,
                total=total,
                series=series,
                assessment=assess(total, series),
                recent_coaching=[t for _, t in sorted(coaching[name], reverse=True)[:3]],
                recent_calls=sorted(calls[name], key=lambda x: (x.when, x.conversation_id), reverse=True)[:8],
                is_current=total.period == current,
            )
        )
    people.sort(key=lambda p: (-p.total.conversations, p.name.lower()))
    technique_stats = [
        TechniqueStat(
            technique=t,
            attempts=n,
            accepted=acc,
            rejected=rej,
            acceptance_rate=round(acc / (acc + rej), 3) if acc + rej else None,
            people=len(tech_people[t]),
        )
        for t, (n, acc, rej) in tech_acc.items()
    ]
    technique_stats.sort(key=lambda s: (-s.attempts, s.technique))
    return Dashboard(
        technique_stats=technique_stats,
        period=period,
        people=people,
        unassigned=sorted(unassigned.values(), key=lambda u: u.created_at, reverse=True),
        unassigned_conversations=sum(u.conversations for u in unassigned.values()),
        current_period=current,
        jobs_counted=counted,
        jobs_skipped=skipped,
    )


def build_roster(storage: Storage) -> list[RosterEntry]:
    """Every known employee (display names, merged duplicates folded together) with the number of
    distinct completed recordings they appear in. Names that only exist as an upload hint or a
    stored assignment are included, with 0 if no readable report mentions them yet."""
    identity = _Identity.load(storage, _all_statuses(storage))
    seen: dict[str, set[str]] = {}
    for status, raw in _completed_reports(storage):
        report = jobs.parse_report(raw)
        if report is None:
            continue
        for _c, _sp, name in _iter_person_labels(report, status, identity):
            if name:
                seen.setdefault(name, set()).add(status.job_id)
    names: dict[str, str] = {}  # casefolded -> display, after following merges
    for shown in list(identity.display.values()):
        canonical = identity.canon(shown)
        names.setdefault(canonical.casefold(), canonical)
    return [
        RosterEntry(name=n, recordings=len(seen.get(n, ())))
        for n in sorted(names.values(), key=lambda v: (v.casefold(), v))
    ]


def build_person_recordings(storage: Storage, name: str) -> list[RecordingSummary]:
    """Every completed recording this person appears in, newest first - not period-bucketed and
    not capped, unlike `PersonSummary.recent_calls`, so a UI can let someone jump to any of their
    recordings rather than only the last 8 in the latest period.
    """
    identity = _Identity.load(storage, _all_statuses(storage))
    wanted = identity.canon(name).casefold()
    per_job: dict[str, _Acc] = {}
    meta: dict[str, tuple[str, str]] = {}  # job_id -> (filename, created_at)

    for status, raw in _completed_reports(storage):
        report = jobs.parse_report(raw)
        if report is None:
            continue
        for c, sp, resolved in _iter_person_labels(report, status, identity):
            if not wanted or not resolved or resolved.casefold() != wanted:
                continue
            per_job.setdefault(status.job_id, _Acc()).add(status.job_id, c, sp)
            meta[status.job_id] = (status.filename, status.created_at)

    recordings = [
        RecordingSummary(
            job_id=job_id,
            filename=meta[job_id][0],
            created_at=meta[job_id][1],
            # `Bucket.period` is documented as a period_label()-shaped string ("2026-10-14",
            # not a full timestamp) - this is a single job, not a period bucket, so the day it
            # was recorded on is the closest equivalent, not the raw created_at.
            stats=acc.bucket(period_label(datetime.fromisoformat(meta[job_id][1]), "day")),
        )
        for job_id, acc in per_job.items()
    ]
    recordings.sort(key=lambda r: r.created_at, reverse=True)
    return recordings
