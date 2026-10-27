"""Does the app's 48k MP3 preprocessing change diarization/script? Same API call, different input file."""
import json, re, sys
from pathlib import Path
from openai import OpenAI
c = OpenAI(); D = Path(__file__).parent
for name, f in [(a.split(":")[0], a.split(":")[1]) for a in sys.argv[1:]]:
    truth = json.load(open(D / "audio" / f"{name}.truth.json"))
    with open(f, "rb") as fh:
        r = c.audio.transcriptions.create(model="gpt-4o-transcribe-diarize", file=fh, response_format="diarized_json", chunking_strategy="auto")
    text = " ".join(s.text for s in r.segments)
    print(f"{name:22} {Path(f).suffix:5} speakers={len({s.speaker for s in r.segments})} (true {len({x['speaker'] for x in truth})}) arabic={len(re.findall(r'[؀-ۿ]', text))} latin={len(re.findall(r'[A-Za-z]', text))}")
