"""Build 3 bilingual (Gulf Arabic + English) sales recordings with one TTS voice per person.

Voices come from game-of-tones (openai/gpt-4o-mini-tts). Each recording is the turns spoken
in order with 0.5 s of silence between them. Ground truth goes next to the audio.
Arabic text is hand-written and needs native review.
Run: python testdata/arabic/gen_audio.py   (needs OPENAI_API_KEY in the environment)
"""
import json
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GOT = Path("/Users/sookieai/Documents/code/accelerators/game-of-tones")
OUT = Path(__file__).parent / "audio"
MODEL = "openai/gpt-4o-mini-tts"

VOICES = {  # person -> (voice, role)
    "Faisal": ("onyx", "salesperson"),
    "Khalid": ("echo", "salesperson"),
    "Noura": ("coral", "salesperson"),
    "Abdullah": ("ash", "customer"),
    "Sara": ("shimmer", "customer"),
    "Mansour": ("fable", "customer"),
    "Lama": ("nova", "customer"),
}

R1 = [  # electronics retail, two customers back to back
    ("Faisal", "السلام عليكم، أهلاً وسهلاً في المتجر. كيف أقدر أخدمك؟"),
    ("Abdullah", "وعليكم السلام. أبغى تلفزيون جديد للصالة، يعني حوالي خمسة وخمسين بوصة."),
    ("Faisal", "ممتاز. عندنا Samsung Crystal UHD بسعر ألفين وتسعمئة ريال، وعليه عرض هالأسبوع."),
    ("Abdullah", "طيب، وش الفرق بينه وبين الـ QLED؟"),
    ("Faisal", "The QLED has better brightness and colours, بس سعره أعلى، حوالي ثلاثة آلاف وتسعمئة ريال."),
    ("Abdullah", "لا، الأول يكفيني. الميزانية عندي ثلاثة آلاف بالكثير."),
    ("Faisal", "تمام. بالمناسبة، عندنا كفالة ممتدة سنتين إضافيتين بس بمئتين وخمسين ريال، وتغطي الشاشة كاملة. تبغى أضيفها؟"),
    ("Abdullah", "هم، وش اللي تغطيه بالضبط؟"),
    ("Faisal", "أي عطل مصنعي، and also free home installation and wall mounting."),
    ("Abdullah", "طيب حلو. أضفها. وكم السعر الإجمالي؟"),
    ("Faisal", "ألفين وتسعمئة زائد مئتين وخمسين، المجموع ثلاثة آلاف ومئة وخمسين ريال شامل الضريبة."),
    ("Abdullah", "تمام، خذها بالبطاقة. شكراً لك."),
    ("Faisal", "العفو، تشرفنا. Have a great day!"),
    ("Sara", "السلام عليكم. My phone charger stopped working، اشتريته من عندكم قبل أسبوعين."),
    ("Faisal", "أهلاً. أكيد نستبدله لك. معك الفاتورة؟"),
    ("Sara", "Yes, here it is. بس الصراحة أنا متضايقة، هذا ثالث شاحن يخرب."),
    ("Faisal", "أعتذر منك. خذي هذا الشاحن الجديد، وأنصحك بشاحن Anker الأصلي، سعره تسعة وتسعون ريال وأقوى بكثير."),
    ("Sara", "لا شكراً، أنا بس أبغى أستبدل. ما أبغى أشتري شي ثاني."),
    ("Faisal", "تمام، ما في مشكلة. تفضلي الشاحن الجديد، ونتمنى لك يوم سعيد."),
    ("Sara", "شكراً."),
]

R2 = [  # car showroom, pushy upsell, customer leaves unconvinced
    ("Khalid", "أهلاً أهلاً أبو فهد! Welcome to Al-Dosari Motors. تبغى سيارة عائلية؟"),
    ("Mansour", "أهلاً. إي، أدور على SUV، الحين عندي سيدان وصغيرة على العيال."),
    ("Khalid", "عندي Toyota Land Cruiser موديل ألفين وستة وعشرين، بثلاثمئة وعشرين ألف ريال."),
    ("Mansour", "مرة غالية. ما عندي هالميزانية. أقصى شي مئتين ألف."),
    ("Khalid", "طيب، عندنا Highlander بمئتين وخمسة وعشرين ألف، ونقدر نقسطها. كم تبغى دفعة أولى؟"),
    ("Mansour", "ما أبغى تقسيط، أبغى كاش، بس أول أشوف السيارة."),
    ("Khalid", "أكيد، تفضل. And this one has the panoramic roof, leather seats, everything."),
    ("Mansour", "حلوة. وش المحرك؟"),
    ("Khalid", "ثلاثة ونص لتر V6. بالمناسبة، ما تبغى تضيف حزمة الحماية الكاملة؟ بخمسة عشر ألف ريال، الحين بس."),
    ("Mansour", "لا، ما أبغاها."),
    ("Khalid", "طيب بس فكر، السيارة الجديدة لازم تنحمى. الحماية الذهبية فيها ضمان الطلاء والزجاج."),
    ("Mansour", "قلت لا، شكراً."),
    ("Khalid", "يا أخي بتندم! أغلب زبائننا يأخذونها. على الأقل خذ التأمين الشامل من عندنا؟"),
    ("Mansour", "أنا قلت لك ما أبغى! أبغى بس أعرف السعر النهائي."),
    ("Khalid", "طيب طيب، آسف. السعر النهائي مئتين وخمسة وعشرين ألف ريال."),
    ("Mansour", "I need to think about it. بكلمك بعدين."),
    ("Khalid", "تمام، تفضل كرتي."),
]

R3 = [  # perfume boutique, good consultative upsell
    ("Noura", "مساء الخير، أهلاً فيك في Oud Palace. تدورين على شي معين؟"),
    ("Lama", "مساء النور. أبغى عطر هدية لزوجي، عيد ميلاده الأسبوع الجاي."),
    ("Noura", "الله يبارك له. وش يحب؟ ريحة خشبية ولا فرنسية خفيفة؟"),
    ("Lama", "هو يحب العود، بس مو قوي مرة."),
    ("Noura", "عندي Royal Oud، عود كمبودي مع لمسة ورد، ويجي بمئتين وثمانين ريال لمئة ملل."),
    ("Lama", "Can I smell it? الله، ريحته حلوة."),
    ("Noura", "Exactly. والحين لو تبغين هدية متكاملة، نقدر نضيف دهن عود ثلاث مل مع علبة هدية فاخرة، بس بمئة وعشرين ريال زيادة."),
    ("Lama", "هم... كم يصير المجموع؟"),
    ("Noura", "أربعمئة ريال بالتمام، وعليه تغليف مجاني باسمه."),
    ("Lama", "ممتاز، خلاص أخذها. اسمه عبدالرحمن."),
    ("Noura", "تم. بتدفعين كاش ولا بطاقة؟"),
    ("Lama", "بطاقة. Thank you so much, you were really helpful!"),
    ("Noura", "العفو حبيبتي، وكل عام وهو بخير."),
]

R4 = [  # busy phone shop: 2 salespeople, 4 customers in one recording
    ("Faisal", "أهلاً وسهلاً، تفضلوا. How can I help you?"),
    ("Abdullah", "السلام عليكم. أبغى جوال جديد، عندي ميزانية ألفين ريال."),
    ("Faisal", "عندي Galaxy A56 بألف وتسعمئة ريال. وبالمناسبة، تبغى معه جراب وحماية شاشة بمئة ريال؟"),
    ("Abdullah", "ما أبغى إضافات، بس الجوال."),
    ("Noura", "أهلاً أختي، كيف أخدمك؟"),
    ("Sara", "I want to return this tablet. الشاشة فيها خط، واشتريتها قبل ثلاثة أيام."),
    ("Noura", "أعتذر جداً. نبدلها لك فوراً. وإذا تبغين، عندنا ضمان حماية الأجهزة بثلاثمئة ريال في السنة."),
    ("Sara", "أكيد أبغى، خصوصاً بعد اللي صار. Thank you, you are very kind."),
    ("Faisal", "تفضل أبو سلطان، وش تحتاج؟"),
    ("Mansour", "أبغى آيفون، الأحدث. كم سعره؟"),
    ("Faisal", "iPhone 17 Pro بخمسة آلاف وثمانمئة ريال. نقدر نقسطه على اثني عشر شهر بدون فوائد."),
    ("Mansour", "طيب، أخذه. وأبغى الشاحن اللاسلكي معه."),
    ("Faisal", "ممتاز، الشاحن بمئة وتسعين ريال. المجموع ستة آلاف وتسعة وثمانين ريال."),
    ("Lama", "Excuse me, عندكم سماعات AirPods؟ هدية لأختي."),
    ("Noura", "أكيد، عندنا AirPods Pro بتسعمئة وتسعين ريال. وعليها تغليف هدية مجاني."),
    ("Lama", "حلو، خذيها. بالبطاقة."),
    ("Noura", "تم. شكراً لك، وكل عام وأنتِ بخير."),
    ("Abdullah", "طيب، خلاص أخذ الجوال بس. وين الكاشير؟"),
    ("Faisal", "هناك على يمينك، تفضل. Have a great day!"),
]

RECORDINGS = {
    "r4_busy_phone_shop": R4,
    "r1_electronics_faisal": R1,
    "r2_cars_khalid": R2,
    "r3_perfume_noura": R3,
}


def speak(job):
    path, who, text = job
    voice = VOICES[who][0]
    if path.exists():
        return path
    for attempt in range(3):
        r = subprocess.run(
            ["uv", "run", "--project", str(GOT), "got", "speak", text, "--model", MODEL,
             "--voice", voice, "--format", "wav", "-o", str(path)],
            capture_output=True, text=True, cwd=GOT,
        )
        if r.returncode == 0:
            return path
    raise RuntimeError(f"{path.name}: {r.stdout[-400:]} {r.stderr[-400:]}")


def join(paths, out):
    params = None
    with wave.open(str(out), "wb") as w:
        for p in paths:
            with wave.open(str(p)) as r:
                if params is None:
                    params = r.getparams()
                    w.setparams(params)
                    gap = b"\x00" * (r.getframerate() * 2 // 2)  # 0.5 s, 16-bit mono
                w.writeframes(r.readframes(r.getnframes()))
                w.writeframes(gap)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    RECORDINGS_TODO = {n: t for n, t in RECORDINGS.items() if not (OUT / f"{n}.wav").exists()}
    for name, turns in RECORDINGS_TODO.items():
        for i, (who, text) in enumerate(turns):
            jobs.append((OUT / f"{name}_{i:02d}.wav", who, text))
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(speak, jobs))
    for name, turns in RECORDINGS_TODO.items():
        parts = [OUT / f"{name}_{i:02d}.wav" for i in range(len(turns))]
        join(parts, OUT / f"{name}.wav")
        for p in parts:
            p.unlink()
        truth = [{"speaker": w, "role": VOICES[w][1], "voice": VOICES[w][0], "text": t} for w, t in turns]
        (OUT / f"{name}.truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1))
    print("done", sorted(p.name for p in OUT.glob("*.wav")))


if __name__ == "__main__":
    main()
