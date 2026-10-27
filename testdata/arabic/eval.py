"""Score transcripts from the running app against ground truth: WER, speakers, roles, upsell."""
import json, re, sys, urllib.request
from pathlib import Path
D = Path(__file__).parent
def norm(s):
    s = re.sub(r"[ً-ٰٟـ]", "", s)           # tashkeel, tatweel
    s = re.sub("[إأآٱ]", "ا", s).replace("ى", "ي").replace("ة", "ه")
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return s.split()
def wer(ref, hyp):
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        p, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            p, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, p + (r != h))
    return d[-1] / max(len(ref), 1)
def script_ratio(s):
    a = len(re.findall(r"[؀-ۿ]", s)); l = len(re.findall(r"[A-Za-z]", s))
    return a, l
jobs = json.load(open(sys.argv[1]))  # {name: [transcript.json, report.json]}
for name, (tp, rp) in jobs.items():
    truth = json.load(open(D / "audio" / f"{name}.truth.json"))
    t = json.load(open(tp))["transcript"]; r = json.load(open(rp))
    segs = t["segments"]; hyp = " ".join(s["text"] for s in segs)
    ref = " ".join(x["text"] for x in truth)
    spk = sorted({s["speaker"] for s in segs})
    a, l = script_ratio(hyp); ta, tl = script_ratio(ref)
    print(f"== {name}\n  WER(normalised) {wer(norm(ref), norm(hyp)):.2f}   ref words {len(norm(ref))} hyp words {len(norm(hyp))}")
    print(f"  speakers true {len({x['speaker'] for x in truth})} detected {len(spk)} {spk}  segments {len(segs)} vs true turns {len(truth)}")
    print(f"  Arabic letters ref/hyp {ta}/{a}   Latin letters ref/hyp {tl}/{l}")
    print(f"  conversations {len(r['conversations'])}  salespeople {[ (p.get('name') or p.get('label')) for p in r['salespeople']]}")
