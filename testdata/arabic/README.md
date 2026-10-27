# Arabic/English test recordings

Four synthetic Gulf Arabic + English sales recordings, one TTS voice per person (game-of-tones, `gpt-4o-mini-tts`).

| File | True speakers | Scenario |
|---|---|---|
| `audio/r1_electronics_faisal.wav` | 3 | Electronics retail, two customers back to back |
| `audio/r2_cars_khalid.wav` | 2 | Car showroom, pushy upsell, customer declines |
| `audio/r3_perfume_noura.wav` | 2 | Perfume boutique, consultative upsell accepted |
| `audio/r4_busy_phone_shop.wav` | 6 | Two salespeople, four customers in one recording |

- `audio/*.truth.json`: ground truth (speaker, role, voice, text per turn).
- `gen_audio.py`: regenerates the audio (needs OPENAI_API_KEY and game-of-tones; path is hard-coded). Arabic text is hand-written and needs native review.
- `eval.py`, `ablate*.py`, `abl_*.json`: ASR language-hint ablation scripts and results; see `docs/arabic-asr-findings.md`.
- `smoke/`: short smoke clip.
- Job stores from test runs (`store*/`) are not committed.

Findings and limits: `docs/arabic-bilingual-test.md`.
