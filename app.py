from flask import Flask, request, jsonify
import requests
import os
import logging
import urllib.parse
import time
import random
import re
from datetime import datetime

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
ADMIN_CHAT_ID      = os.environ.get('ADMIN_CHAT_ID')   # Feature 11: broadcast

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POLLINATIONS_URL = (
    "https://image.pollinations.ai/prompt/{prompt}"
    "?model={model}&width={width}&height={height}"
    "&seed={seed}&nologo=true&enhance={enhance}"
)

# =========================================================
# STATIC DATA
# =========================================================
MODELS = {
    "1": {"name": "FLUX ⚡",         "id": "flux",          "desc": "Best quality (Recommended)"},
    "2": {"name": "FLUX Realism 📸", "id": "flux-realism",  "desc": "Photorealistic images"},
    "3": {"name": "FLUX Anime 🎌",   "id": "flux-anime",    "desc": "Anime style images"},
    "4": {"name": "Turbo ⚡⚡",       "id": "turbo",         "desc": "Fastest generation"},
}

SIZES = {
    "1": {"name": "Square 1:1",    "w": 1024, "h": 1024},
    "2": {"name": "Portrait 2:3",  "w": 832,  "h": 1216},
    "3": {"name": "Landscape 3:2", "w": 1216, "h": 832},
    "4": {"name": "Wide 16:9",     "w": 1344, "h": 768},
}

# Feature 5 — Platform ratios
RATIOS = {
    "1": {"name": "Instagram 4:5 📸",  "w": 864,  "h": 1080},
    "2": {"name": "Twitter/X 16:9 🐦", "w": 1344, "h": 756},
    "3": {"name": "Wallpaper 21:9 🖥️", "w": 1512, "h": 648},
    "4": {"name": "Story 9:16 📱",     "w": 768,  "h": 1344},
    "5": {"name": "Pinterest 2:3 📌",  "w": 832,  "h": 1216},
}

# Feature 2 — Style presets
STYLE_PRESETS = {
    "1": {"name": "🎬 Cinematic",  "suffix": "cinematic lighting, dramatic atmosphere, film grain, 4K"},
    "2": {"name": "🎌 Anime",      "suffix": "anime style, vibrant colors, detailed, Studio Ghibli inspired"},
    "3": {"name": "📸 Realistic",  "suffix": "photorealistic, hyperdetailed, DSLR photo, sharp focus, 8K"},
    "4": {"name": "🌆 Neon City",  "suffix": "neon lights, cyberpunk, futuristic city, rain reflections, night"},
    "5": {"name": "🧪 Surreal",    "suffix": "surrealist art, dreamlike, Salvador Dali inspired, ethereal"},
    "6": {"name": "🖌️ Oil Paint",  "suffix": "oil painting, classical art, renaissance style, detailed brushwork"},
    "7": {"name": "❌ No Style",   "suffix": ""},
}

# Feature 12 — Random prompts pool
RANDOM_PROMPTS = [
    "a dragon made of crystal soaring over a neon Tokyo skyline, cinematic",
    "an ancient Indian temple floating in space surrounded by stars, mystical lighting",
    "a steampunk elephant with brass gears and glowing eyes in a Victorian city",
    "underwater city of Atlantis with glowing bioluminescent creatures, 4K",
    "a samurai warrior standing on a mountain during a cherry blossom storm, cinematic",
    "a robot monk meditating in a futuristic monastery, soft golden light",
    "a magical library inside a giant tree filled with fireflies, fantasy art",
    "a phoenix rising from the ocean at sunset, epic scale, 8K",
    "street market in ancient Hampi, vibrant colors, photorealistic",
    "a lone astronaut discovering a blooming flower garden on Mars",
    "a wolf made entirely of northern lights running through a snowy forest",
    "an Indian classical dancer performing on a glass stage above the clouds",
    "a giant whale swimming through clouds at golden hour, surreal",
    "a cyberpunk Mysore palace with neon lights and holograms at night",
    "a child reading a glowing book in a magical treehouse at night",
    "a tiger made of thunderstorms leaping across mountain peaks",
    "Hampi ruins reimagined as a futuristic sci-fi city, cinematic",
    "a mermaid made of moonlight swimming in a bioluminescent ocean",
]

# Feature 13 — Daily challenge themes (cycles by day of year)
DAILY_THEMES = [
    "🌌 Space + Ancient Civilization",
    "🌊 Underwater Fantasy World",
    "🔥 Fire vs Ice",
    "🌸 Nature Meets Technology",
    "🏛️ Mythology Reimagined",
    "🤖 Robots Living in Nature",
    "🌆 Futuristic India 2100",
    "🧙 Magic + Science",
    "🦋 Micro World Macro View",
    "🌅 Golden Hour Everywhere",
    "🎭 Two Worlds Collide",
    "🦁 Animals as Ancient Warriors",
]

# =========================================================
# USER STATE  (in-memory — resets on server restart)
# =========================================================
user_model_choice = {}   # chat_id -> "1".."4"
user_size_choice  = {}   # chat_id -> "1".."4"
user_ratio        = {}   # chat_id -> {"name","w","h"}  overrides size
user_enhance      = {}   # chat_id -> bool  (default True)
user_style        = {}   # chat_id -> "1".."7"
user_last_prompt  = {}   # chat_id -> str   for Variation / Upscale
user_all_ids      = set()  # Feature 11: broadcast list

# =========================================================
# STATS  (Feature 9)
# =========================================================
stats = {
    "total":       0,
    "model_usage": {k: 0 for k in MODELS},
    "since":       datetime.now().strftime("%Y-%m-%d %H:%M"),
}

# =========================================================
# HELPERS
# =========================================================
def telegram_api(method, data=None, files=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    try:
        if files:
            resp = requests.post(url, data=data, files=files, timeout=30)
        elif data:
            resp = requests.post(url, json=data, timeout=30)
        else:
            resp = requests.get(url, timeout=30)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        logger.error(f"Telegram API error: {e}")
        return None


def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_api("sendMessage", payload)


def generate_image(prompt, model_id, width=1024, height=1024, enhance=True):
    seed    = random.randint(1, 999999)
    encoded = urllib.parse.quote(prompt)
    url     = POLLINATIONS_URL.format(
        prompt=encoded, model=model_id,
        width=width, height=height,
        seed=seed, enhance="true" if enhance else "false"
    )
    logger.info(f"Pollinations → {url}")

    DELAYS = [5, 10, 20, 30]
    for attempt in range(4):
        try:
            resp = requests.get(url, timeout=120)
            logger.info(f"Attempt {attempt+1} — HTTP {resp.status_code}")
            if resp.status_code == 200:
                ct = resp.headers.get("Content-Type", "")
                if "image" in ct or len(resp.content) > 1000:
                    return resp.content, None
                return None, "❌ Image data ಬರಲಿಲ್ಲ. ಮತ್ತೆ try ಮಾಡಿ."
            elif resp.status_code == 429:
                wait = DELAYS[attempt] if attempt < len(DELAYS) else 30
                logger.warning(f"Rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            else:
                return None, f"❌ Error {resp.status_code}. ಮತ್ತೆ try ಮಾಡಿ."
        except requests.Timeout:
            if attempt < 3:
                time.sleep(DELAYS[attempt])
                continue
            return None, "⏰ Timeout. ಮತ್ತೆ try ಮಾಡಿ."
        except Exception as e:
            return None, f"❌ {e}"

    return None, "❌ ಹಲವು ಬಾರಿ try ಮಾಡಿದರೂ ಆಗಲಿಲ್ಲ. ಸ್ವಲ್ಪ ಕಾಯಿ ಮತ್ತೆ try ಮಾಡಿ."


def get_size(chat_id):
    """Return (name, w, h) — ratio overrides /size choice."""
    if chat_id in user_ratio:
        r = user_ratio[chat_id]
        return r["name"], r["w"], r["h"]
    key = user_size_choice.get(chat_id, "1")
    s   = SIZES[key]
    return s["name"], s["w"], s["h"]


def styled_prompt(prompt, chat_id):
    """Append style suffix if a non-default style is active."""
    key    = user_style.get(chat_id, "7")
    suffix = STYLE_PRESETS.get(key, STYLE_PRESETS["7"])["suffix"]
    return f"{prompt}, {suffix}" if suffix else prompt


def do_generate(chat_id, prompt, upscale=False):
    """Core pipeline used by all generation paths."""
    model_key            = user_model_choice.get(chat_id, "1")
    model                = MODELS[model_key]
    enhance              = user_enhance.get(chat_id, True)
    size_name, w, h      = get_size(chat_id)

    # Feature 14: upscale doubles resolution (max 2048)
    if upscale:
        w = min(w * 2, 2048)
        h = min(h * 2, 2048)

    style_key  = user_style.get(chat_id, "7")
    style_name = STYLE_PRESETS[style_key]["name"] if style_key != "7" else ""
    full_prompt = styled_prompt(prompt, chat_id)

    enhance_tag = "✨ Enhance ON" if enhance else "🔇 Enhance OFF"
    upscale_tag = " | 🔍 2x" if upscale else ""
    style_tag   = f" | {style_name}" if style_name else ""

    send_message(chat_id,
        f"🎨 <b>{model['name']}</b> | 📐 {size_name}{upscale_tag}{style_tag}\n"
        f"{enhance_tag}\n"
        f"📝 <i>{prompt[:100]}</i>\n\n"
        f"⏳ Generate ಆಗ್ತಿದೆ..."
    )

    image_data, error = generate_image(full_prompt, model["id"], w, h, enhance)

    if image_data:
        stats["total"] += 1
        stats["model_usage"][model_key] = stats["model_usage"].get(model_key, 0) + 1
        user_last_prompt[chat_id] = prompt

        # Feature 3 & 14 — action buttons under every image
        markup = {
            "inline_keyboard": [[
                {"text": "🔄 Variation",   "callback_data": f"vary_{chat_id}"},
                {"text": "🔍 Upscale 2x", "callback_data": f"upscale_{chat_id}"},
            ]]
        }
        files  = {"photo": ("image.jpg", image_data, "image/jpeg")}
        result = telegram_api("sendPhoto", {
            "chat_id":      chat_id,
            "caption":      f"✅ <b>{model['name']}</b> | {size_name}\n📝 {prompt[:200]}",
            "parse_mode":   "HTML",
            "reply_markup": markup,
        }, files=files)
        if not result or not result.get("ok"):
            files2 = {"document": ("image.jpg", image_data, "image/jpeg")}
            telegram_api("sendDocument", {"chat_id": chat_id}, files=files2)
    else:
        send_message(chat_id, error or "❌ Image generate ಆಗಲಿಲ್ಲ.")


# =========================================================
# KEYBOARD BUILDERS
# =========================================================
def models_keyboard():
    return {"inline_keyboard": [
        [{"text": f"{v['name']} — {v['desc']}", "callback_data": f"model_{k}"}]
        for k, v in MODELS.items()
    ]}

def sizes_keyboard():
    return {"inline_keyboard": [
        [{"text": f"{v['name']} ({v['w']}×{v['h']})", "callback_data": f"size_{k}"}]
        for k, v in SIZES.items()
    ]}

def ratios_keyboard():
    return {"inline_keyboard": [
        [{"text": f"{v['name']} ({v['w']}×{v['h']})", "callback_data": f"ratio_{k}"}]
        for k, v in RATIOS.items()
    ]}

def styles_keyboard():
    items   = list(STYLE_PRESETS.items())
    buttons = []
    for i in range(0, len(items), 2):
        row = []
        for k, v in items[i:i+2]:
            row.append({"text": v["name"], "callback_data": f"style_{k}"})
        buttons.append(row)
    return {"inline_keyboard": buttons}


# =========================================================
# WEBHOOK
# =========================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()

        # ── Callback button clicks ───────────────────────────────────────
        if "callback_query" in data:
            cb      = data["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            cb_data = cb.get("data", "")
            cb_id   = cb["id"]

            if cb_data.startswith("model_"):
                key = cb_data[6:]
                if key in MODELS:
                    user_model_choice[chat_id] = key
                    m = MODELS[key]
                    telegram_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"✅ {m['name']} selected!"})
                    send_message(chat_id, f"✅ Model: <b>{m['name']}</b>\n\n💡 ಈಗ prompt type ಮಾಡಿ!")

            elif cb_data.startswith("size_"):
                key = cb_data[5:]
                if key in SIZES:
                    user_size_choice[chat_id] = key
                    user_ratio.pop(chat_id, None)
                    s = SIZES[key]
                    telegram_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"✅ {s['name']} selected!"})
                    send_message(chat_id, f"✅ Size: <b>{s['name']}</b> ({s['w']}×{s['h']})\n\n💡 ಈಗ prompt type ಮಾಡಿ!")

            # Feature 5
            elif cb_data.startswith("ratio_"):
                key = cb_data[6:]
                if key in RATIOS:
                    r = RATIOS[key]
                    user_ratio[chat_id] = r
                    telegram_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"✅ {r['name']} selected!"})
                    send_message(chat_id, f"✅ Ratio: <b>{r['name']}</b> ({r['w']}×{r['h']})\n\n💡 ಈಗ prompt type ಮಾಡಿ!")

            # Feature 2
            elif cb_data.startswith("style_"):
                key = cb_data[6:]
                if key in STYLE_PRESETS:
                    user_style[chat_id] = key
                    st = STYLE_PRESETS[key]
                    telegram_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"✅ {st['name']} selected!"})
                    preview = f"\n🔍 <i>{st['suffix'][:70]}</i>" if st["suffix"] else ""
                    send_message(chat_id, f"✅ Style: <b>{st['name']}</b>{preview}\n\n💡 ಈಗ prompt type ಮಾಡಿ!")

            # Feature 3 — Variation
            elif cb_data.startswith("vary_"):
                orig_id = int(cb_data[5:])
                telegram_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": "🔄 Variation generate ಆಗ್ತಿದೆ..."})
                last = user_last_prompt.get(orig_id)
                if last:
                    do_generate(chat_id, last)
                else:
                    send_message(chat_id, "⚠️ ಹಿಂದಿನ prompt ಸಿಗಲಿಲ್ಲ. ಮತ್ತೆ type ಮಾಡಿ.")

            # Feature 14 — Upscale button
            elif cb_data.startswith("upscale_"):
                orig_id = int(cb_data[8:])
                telegram_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": "🔍 Upscaling 2x..."})
                last = user_last_prompt.get(orig_id)
                if last:
                    do_generate(chat_id, last, upscale=True)
                else:
                    send_message(chat_id, "⚠️ ಹಿಂದಿನ prompt ಸಿಗಲಿಲ್ಲ. ಮತ್ತೆ type ಮಾಡಿ.")

            return jsonify({"status": "ok"})

        # ── Regular messages ─────────────────────────────────────────────
        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text    = message.get("text", "")

        if not chat_id or not text:
            return jsonify({"status": "ok"})

        user_all_ids.add(chat_id)

        if text.startswith("/start"):
            send_message(chat_id,
                "🤖 <b>CC Pic Bot v6 — AI Image Generator</b>\n\n"
                "⚡ Powered by Pollinations.ai\n"
                "✅ 100% Free • No limits • No credits!\n\n"
                "💬 <b>Just type your prompt — no command needed!</b>\n"
                "<i>Example: beautiful girl, cinematic lighting</i>\n\n"
                "📌 <b>Commands:</b>\n"
                "/model — AI model ಆಯ್ಕೆ\n"
                "/size — Image size ಆಯ್ಕೆ\n"
                "/ratio — Platform ratio (Instagram, Twitter…)\n"
                "/style — Art style preset\n"
                "/enhance — Prompt enhance toggle\n"
                "/random — 🎲 Random surprise image\n"
                "/daily — 🏆 Today's challenge theme\n"
                "/stats — 📊 Usage statistics\n"
                "/models — ಎಲ್ಲಾ models list\n"
                "/help — Full help\n\n"
                "🔁 <b>Batch:</b> <code>3x: sunset over mountains</code>\n"
                "🔄 Image ನಂತರ <b>Variation</b> &amp; <b>Upscale 2x</b> buttons ಇವೆ!"
            )

        elif text.startswith("/help"):
            send_message(chat_id,
                "📖 <b>CC Pic Bot v6 — Help</b>\n\n"
                "💬 <b>Direct typing:</b> Just type your prompt!\n\n"
                "⚙️ <b>Customise:</b>\n"
                "• /model — AI model ಆಯ್ಕೆ\n"
                "• /size — Image dimensions\n"
                "• /ratio — Platform ratio (Instagram 4:5, etc.)\n"
                "• /style — Art style (Cinematic, Anime, Oil Paint…)\n"
                "• /enhance — Enhance toggle (ON/OFF)\n\n"
                "🎯 <b>Generate:</b>\n"
                "• Type any text → instant image\n"
                "• <code>3x: your prompt</code> → 3 variations at once\n"
                "• /random → Surprise me!\n"
                "• /daily → Today's challenge theme\n"
                "• /upscale → Last image 2x ದೊಡ್ಡದು ಮಾಡು\n\n"
                "💡 <b>Prompt Tips:</b>\n"
                "• <i>mountain lake at sunrise, 4K, cinematic</i>\n"
                "• <i>anime girl in rain, neon city, detailed</i>\n"
                "• <i>oil painting of Hampi ruins, golden hour</i>\n\n"
                "⚠️ Rate limit ಬಂದರೆ bot ತಾನೇ retry ಮಾಡುತ್ತದೆ!\n"
                "⚡ Defaults: FLUX • 1024×1024 • Enhance ON"
            )

        elif text.startswith("/models"):
            ml = "\n\n".join(
                f"{k}. <b>{v['name']}</b>\n   └ {v['desc']}" for k, v in MODELS.items()
            )
            send_message(chat_id, f"🎨 <b>Available Models:</b>\n\n{ml}\n\n/model ಬಳಸಿ select ಮಾಡಿ.")

        elif text.startswith("/model"):
            send_message(chat_id, "🎨 <b>Model ಆಯ್ಕೆ ಮಾಡಿ:</b>", reply_markup=models_keyboard())

        elif text.startswith("/size"):
            send_message(chat_id, "📐 <b>Image Size ಆಯ್ಕೆ ಮಾಡಿ:</b>", reply_markup=sizes_keyboard())

        # Feature 5
        elif text.startswith("/ratio"):
            cur     = user_ratio.get(chat_id)
            cur_txt = f"\nCurrent: <b>{cur['name']}</b>" if cur else ""
            send_message(chat_id, f"📱 <b>Platform Ratio ಆಯ್ಕೆ ಮಾಡಿ:</b>{cur_txt}", reply_markup=ratios_keyboard())

        # Feature 2
        elif text.startswith("/style"):
            cur_key  = user_style.get(chat_id, "7")
            cur_name = STYLE_PRESETS[cur_key]["name"]
            send_message(chat_id,
                f"🎭 <b>Style Preset ಆಯ್ಕೆ ಮಾಡಿ:</b>\nCurrent: <b>{cur_name}</b>",
                reply_markup=styles_keyboard()
            )

        # Feature 1
        elif text.startswith("/enhance"):
            cur     = user_enhance.get(chat_id, True)
            new_val = not cur
            user_enhance[chat_id] = new_val
            status  = "✅ ON" if new_val else "❌ OFF"
            send_message(chat_id,
                f"✨ <b>Prompt Enhancement: {status}</b>\n\n"
                + ("Pollinations AI ನಿಮ್ಮ prompt ಅನ್ನು ತಾನೇ improve ಮಾಡುತ್ತದೆ. ✅"
                   if new_val else
                   "Prompt ಯಥಾವತ್ ಉಪಯೋಗಿಸಲಾಗುತ್ತದೆ. ❌")
            )

        # Feature 9
        elif text.startswith("/stats"):
            breakdown = "\n".join(
                f"  {MODELS[k]['name']}: <b>{v}</b> images"
                for k, v in stats["model_usage"].items()
            )
            send_message(chat_id,
                f"📊 <b>CC Pic Bot Stats:</b>\n\n"
                f"🖼️ Total Images: <b>{stats['total']}</b>\n"
                f"👥 Total Users: <b>{len(user_all_ids)}</b>\n"
                f"🕐 Running Since: <b>{stats['since']}</b>\n\n"
                f"🎨 <b>Model Breakdown:</b>\n{breakdown}"
            )

        # Feature 12
        elif text.startswith("/random"):
            rp = random.choice(RANDOM_PROMPTS)
            send_message(chat_id, f"🎲 <b>Random Prompt:</b>\n<i>{rp}</i>")
            do_generate(chat_id, rp)

        # Feature 13
        elif text.startswith("/daily"):
            day   = datetime.now().timetuple().tm_yday
            theme = DAILY_THEMES[day % len(DAILY_THEMES)]
            send_message(chat_id,
                f"🏆 <b>Today's Prompt Challenge:</b>\n\n"
                f"🎯 Theme: <b>{theme}</b>\n\n"
                f"💡 ಈ theme ಬಳಸಿ ನಿಮ್ಮ prompt type ಮಾಡಿ!\n"
                f"<i>Example: ancient Indian warrior in space, nebula background, epic, 8K</i>"
            )

        # Feature 14 (command)
        elif text.startswith("/upscale"):
            last = user_last_prompt.get(chat_id)
            if last:
                send_message(chat_id, f"🔍 <b>Upscale 2x ಮಾಡ್ತಿದ್ದೇನೆ...</b>\n📝 <i>{last[:100]}</i>")
                do_generate(chat_id, last, upscale=True)
            else:
                send_message(chat_id, "⚠️ ಮೊದಲು ಒಂದು image generate ಮಾಡಿ, ನಂತರ /upscale ಬಳಸಿ.")

        # Feature 11
        elif text.startswith("/broadcast"):
            if ADMIN_CHAT_ID and str(chat_id) == str(ADMIN_CHAT_ID):
                msg = text[len("/broadcast"):].strip()
                if msg:
                    success = 0
                    for uid in list(user_all_ids):
                        r = send_message(uid, f"📢 <b>CC Pic Bot Update:</b>\n\n{msg}")
                        if r and r.get("ok"):
                            success += 1
                    send_message(chat_id, f"✅ Broadcast sent to {success}/{len(user_all_ids)} users!")
                else:
                    send_message(chat_id, "⚠️ Message ಕೊಡಿ!\n\n<b>Usage:</b> /broadcast Your message here")
            else:
                send_message(chat_id, "❌ Admin only command.")

        # /generate (backward compat)
        elif text.startswith("/generate"):
            prompt = text[9:].strip()
            if not prompt:
                send_message(chat_id,
                    "⚠️ Prompt ಕೊಡಿ!\n\n"
                    "<b>Example:</b> /generate a beautiful mountain landscape\n\n"
                    "💡 ಅಥವಾ ನೇರ type ಮಾಡಿ — no command needed!"
                )
            else:
                do_generate(chat_id, prompt)

        # Feature 7 (batch) OR plain text prompt
        else:
            batch = re.match(r'^(\d+)x:\s*(.+)$', text.strip(), re.IGNORECASE)
            if batch:
                count  = min(int(batch.group(1)), 4)
                prompt = batch.group(2).strip()
                send_message(chat_id,
                    f"🔁 <b>Batch Generate: {count} images</b>\n"
                    f"📝 <i>{prompt[:100]}</i>\n\n"
                    f"⏳ ಒಂದೊಂದಾಗಿ generate ಮಾಡ್ತೀನಿ..."
                )
                for i in range(count):
                    send_message(chat_id, f"🎨 <b>{i+1}/{count}</b> generating...")
                    do_generate(chat_id, prompt)
            else:
                prompt = text.strip()
                if prompt:
                    do_generate(chat_id, prompt)

        return jsonify({"status": "ok"})

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500


# =========================================================
# ROUTES
# =========================================================
@app.route('/setup')
def setup_webhook():
    webhook_url = request.url_root.rstrip('/') + '/webhook'
    result = telegram_api("setWebhook", {"url": webhook_url})
    if result and result.get('ok'):
        return f"✅ Webhook set: {webhook_url}"
    return f"❌ Failed: {result}"


@app.route('/status')
def status():
    result = telegram_api("getWebhookInfo")
    if result and result.get('ok'):
        info = result.get('result', {})
        return jsonify({
            "webhook_url":     info.get('url'),
            "pending_updates": info.get('pending_update_count'),
            "last_error":      info.get('last_error_message'),
            "total_images":    stats["total"],
            "total_users":     len(user_all_ids),
            "provider":        "Pollinations.ai (Free)",
            "bot_token_set":   bool(TELEGRAM_BOT_TOKEN),
        })
    return jsonify({"error": "Failed"})


@app.route('/')
def index():
    return "🤖 CC Pic Bot v6 running! Visit /setup to configure webhook."


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
