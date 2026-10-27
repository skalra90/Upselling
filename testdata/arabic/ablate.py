"""Call the OpenAI diarize model directly with different hints; report speakers, Latin share, WER."""
import json, os, re, sys
from pathlib import Path
from openai import OpenAI
sys.path.insert(0, str(Path(__file__).parent))
import importlib.util
spec = importlib.util.spec_from_file_location("ev", Path(__file__).parent / "eval.py")
D = Path(__file__).parent
def norm(s):
    s = re.sub(r"[ً-ٰٟـ]", "", s); s = re.sub("[إأآٱ]", "ا", s).replace("ى", "ي").replace("ة", "ه")
    return re.sub(r"[^\w\s]", " ", s.lower()).split()
def wer(ref, hyp):
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        p, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            p, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, p + (r != h))
    return d[-1] / max(len(ref), 1)
c = OpenAI()
variants = {"none": {}, "lang=ar": {"language": "ar"}}
for name in sys.argv[1:]:
    truth = json.load(open(D / "audio" / f"{name}.truth.json")); ref = norm(" ".join(x["text"] for x in truth))
    for vn, kw in variants.items():
        with open(D / "audio" / f"{name}.wav", "rb") as f:
            try:
                r = c.audio.transcriptions.create(model="gpt-4o-transcribe-diarize", file=f, response_format="diarized_json", chunking_strategy="auto", **kw)
            except Exception as e:
                print(name, vn, "ERROR", str(e)[:200]); continue
        segs = r.segments; text = " ".join(s.text for s in segs)
        lat = len(re.findall(r"[A-Za-z]", text)); ar = len(re.findall(r"[؀-ۿ]", text))
        print(f"{name:24} {vn:8} speakers={len({s.speaker for s in segs})} (true {len({x['speaker'] for x in truth})}) segs={len(segs)}/{len(truth)} WER={wer(ref, norm(text)):.2f} arabic={ar} latin={lat}")
        (D / f"abl_{name}_{vn.replace('=','_')}.json").write_text(json.dumps([s.model_dump() for s in segs], ensure_ascii=False, indent=1))
