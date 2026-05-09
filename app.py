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
ADMIN_CHAT_ID      = os.environ.get('ADMIN_CHAT_ID')

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
    "1": {"name": "FLUX ⚡",         "id": "flux",         "desc": "Best quality"},
    "2": {"name": "FLUX Realism 📸", "id": "flux-realism", "desc": "Photorealistic"},
    "3": {"name": "FLUX Anime 🎌",   "id": "flux-anime",   "desc": "Anime style"},
    "4": {"name": "Turbo ⚡⚡",       "id": "turbo",        "desc": "Fastest"},
}

SIZES = {
    "1": {"name": "Square 1:1",    "w": 1024, "h": 1024},
    "2": {"name": "Portrait 2:3",  "w": 832,  "h": 1216},
    "3": {"name": "Landscape 3:2", "w": 1216, "h": 832},
    "4": {"name": "Wide 16:9",     "w": 1344, "h": 768},
}

RATIOS = {
    "1": {"name": "Instagram 4:5 📸",  "w": 864,  "h": 1080},
    "2": {"name": "Twitter/X 16:9 🐦", "w": 1344, "h": 756},
    "3": {"name": "Wallpaper 21:9 🖥️", "w": 1512, "h": 648},
    "4": {"name": "Story 9:16 📱",     "w": 768,  "h": 1344},
    "5": {"name": "Pinterest 2:3 📌",  "w": 832,  "h": 1216},
}

STYLE_PRESETS = {
    "1": {"name": "🎬 Cinematic",  "suffix": "cinematic lighting, dramatic atmosphere, film grain, 4K"},
    "2": {"name": "🎌 Anime",      "suffix": "anime style, vibrant colors, detailed, Studio Ghibli inspired"},
    "3": {"name": "📸 Realistic",  "suffix": "photorealistic, hyperdetailed, DSLR photo, sharp focus, 8K"},
    "4": {"name": "🌆 Neon City",  "suffix": "neon lights, cyberpunk, futuristic city, rain reflections, night"},
    "5": {"name": "🧪 Surreal",    "suffix": "surrealist art, dreamlike, Salvador Dali inspired, ethereal"},
    "6": {"name": "🖌️ Oil Paint",  "suffix": "oil painting, classical art, renaissance style, detailed brushwork"},
    "7": {"name": "❌ No Style",   "suffix": ""},
}

RANDOM_PROMPTS = [
    "a dragon made of crystal soaring over a neon Tokyo skyline, cinematic",
    "an ancient Indian temple floating in space surrounded by stars, mystical lighting",
    "a steampunk elephant with brass gears and glowing eyes in a Victorian city",
    "underwater city of Atlantis with glowing bioluminescent creatures, 4K",
    "a samurai warrior standing on a mountain during a cherry blossom storm",
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
# USER STATE
# =========================================================
user_model_choice = {}
user_size_choice  = {}
user_ratio        = {}
user_enhance      = {}
user_style        = {}
user_last_prompt  = {}
user_all_ids      = set()

# =========================================================
# STATS
# =========================================================
stats = {
    "total":       0,
    "model_usage": {k: 0 for k in MODELS},
    "since":       datetime.now().strftime("%Y-%m-%d %H:%M"),
}

# =========================================================
# MAIN MENU keyboard — always visible at bottom
# =========================================================
MAIN_MENU = {
    "keyboard": [
        ["🎲 Random",      "🏆 Daily Challenge"],
        ["🎨 Style",       "📱 Ratio"],
        ["🤖 Model",       "📐 Size"],
        ["✨ Enhance",     "📊 Stats"],
        ["❓ Help"],
    ],
    "resize_keyboard":   True,
    "one_time_keyboard": False,
    "input_field_placeholder": "Type your prompt here...",
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


def send_message(chat_id, text, reply_markup=None, inline_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if inline_markup:
        payload["reply_markup"] = inline_markup
    elif reply_markup:
        payload["reply_markup"] = reply_markup
    else:
        payload["reply_markup"] = MAIN_MENU   # always show main menu
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
    if chat_id in user_ratio:
        r = user_ratio[chat_id]
        return r["name"], r["w"], r["h"]
    key = user_size_choice.get(chat_id, "1")
    s   = SIZES[key]
    return s["name"], s["w"], s["h"]


def styled_prompt(prompt, chat_id):
    key    = user_style.get(chat_id, "7")
    suffix = STYLE_PRESETS.get(key, STYLE_PRESETS["7"])["suffix"]
    return f"{prompt}, {suffix}" if suffix else prompt


def do_generate(chat_id, prompt, upscale=False):
    model_key       = user_model_choice.get(chat_id, "1")
    model           = MODELS[model_key]
    enhance         = user_enhance.get(chat_id, True)
    size_name, w, h = get_size(chat_id)

    if upscale:
        w = min(w * 2, 2048)
        h = min(h * 2, 2048)

    full_prompt = styled_prompt(prompt, chat_id)

    # ── Simplified status: just 🎨CC_PIC ──
    send_message(chat_id,
        f"🎨CC_PIC\n"
        f"📝 <i>{prompt[:100]}</i>\n"
        f"⏳ Generate ಆಗ್ತಿದೆ..."
    )

    image_data, error = generate_image(full_prompt, model["id"], w, h, enhance)

    if image_data:
        stats["total"] += 1
        stats["model_usage"][model_key] = stats["model_usage"].get(model_key, 0) + 1
        user_last_prompt[chat_id] = prompt

        # Inline buttons under the image
        inline_buttons = {
            "inline_keyboard": [[
                {"text": "🔄 Variation",   "callback_data": f"vary_{chat_id}"},
                {"text": "🔍 Upscale 2x", "callback_data": f"upscale_{chat_id}"},
            ]]
        }
        files  = {"photo": ("image.jpg", image_data, "image/jpeg")}
        result = telegram_api("sendPhoto", {
            "chat_id":      chat_id,
            "caption":      f"🎨CC_PIC\n📝 {prompt[:200]}",
            "parse_mode":   "HTML",
            "reply_markup": inline_buttons,
        }, files=files)
        if not result or not result.get("ok"):
            files2 = {"document": ("image.jpg", image_data, "image/jpeg")}
            telegram_api("sendDocument", {"chat_id": chat_id}, files=files2)
    else:
        send_message(chat_id, error or "❌ Image generate ಆಗಲಿಲ್ಲ.")


# =========================================================
# INLINE KEYBOARD BUILDERS  (for settings menus)
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
                    send_message(chat_id, f"✅ Model: <b>{m['name']}</b>\n💡 ಈಗ prompt type ಮಾಡಿ!")

            elif cb_data.startswith("size_"):
                key = cb_data[5:]
                if key in SIZES:
                    user_size_choice[chat_id] = key
                    user_ratio.pop(chat_id, None)
                    s = SIZES[key]
                    telegram_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"✅ {s['name']} selected!"})
                    send_message(chat_id, f"✅ Size: <b>{s['name']}</b> ({s['w']}×{s['h']})\n💡 ಈಗ prompt type ಮಾಡಿ!")

            elif cb_data.startswith("ratio_"):
                key = cb_data[6:]
                if key in RATIOS:
                    r = RATIOS[key]
                    user_ratio[chat_id] = r
                    telegram_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"✅ {r['name']} selected!"})
                    send_message(chat_id, f"✅ Ratio: <b>{r['name']}</b> ({r['w']}×{r['h']})\n💡 ಈಗ prompt type ಮಾಡಿ!")

            elif cb_data.startswith("style_"):
                key = cb_data[6:]
                if key in STYLE_PRESETS:
                    user_style[chat_id] = key
                    st = STYLE_PRESETS[key]
                    telegram_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"✅ {st['name']} selected!"})
                    preview = f"\n🔍 <i>{st['suffix'][:70]}</i>" if st["suffix"] else ""
                    send_message(chat_id, f"✅ Style: <b>{st['name']}</b>{preview}\n💡 ಈಗ prompt type ಮಾಡಿ!")

            elif cb_data.startswith("vary_"):
                orig_id = int(cb_data[5:])
                telegram_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": "🔄 Variation generate ಆಗ್ತಿದೆ..."})
                last = user_last_prompt.get(orig_id)
                if last:
                    do_generate(chat_id, last)
                else:
                    send_message(chat_id, "⚠️ ಹಿಂದಿನ prompt ಸಿಗಲಿಲ್ಲ. ಮತ್ತೆ type ಮಾಡಿ.")

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

        # ── /start ───────────────────────────────────────────────────────
        if text.startswith("/start"):
            send_message(chat_id,
                "🎨 <b>CC_PIC — AI Image Generator</b>\n\n"
                "⚡ Powered by Pollinations.ai\n"
                "✅ 100% Free • No limits!\n\n"
                "💬 <b>Just type your prompt!</b>\n"
                "<i>Example: beautiful mountain at sunset</i>\n\n"
                "👇 ಕೆಳಗಿನ buttons ಉಪಯೋಗಿಸಿ settings change ಮಾಡಿ."
            )

        # ── /help ────────────────────────────────────────────────────────
        elif text in ["❓ Help", "/help"]:
            send_message(chat_id,
                "📖 <b>CC_PIC Help</b>\n\n"
                "💬 <b>Image Generate:</b>\n"
                "Just type your prompt directly!\n"
                "<code>3x: sunset mountains</code> → 3 images\n\n"
                "🎛️ <b>Settings Buttons:</b>\n"
                "🤖 Model — AI model ಆಯ್ಕೆ\n"
                "📐 Size — Image dimensions\n"
                "📱 Ratio — Platform sizes\n"
                "🎨 Style — Art style\n"
                "✨ Enhance — Prompt boost toggle\n\n"
                "🎯 <b>Quick Actions:</b>\n"
                "🎲 Random — Surprise image\n"
                "🏆 Daily Challenge — Today's theme\n"
                "📊 Stats — Usage stats\n\n"
                "🔄 <b>After every image:</b>\n"
                "Variation + Upscale 2x buttons ಇವೆ!\n\n"
                "⚡ Defaults: FLUX • 1024×1024 • Enhance ON"
            )

        # ── 🤖 Model ─────────────────────────────────────────────────────
        elif text in ["🤖 Model", "/model"]:
            cur_key  = user_model_choice.get(chat_id, "1")
            cur_name = MODELS[cur_key]["name"]
            send_message(chat_id,
                f"🤖 <b>Model ಆಯ್ಕೆ ಮಾಡಿ:</b>\nCurrent: <b>{cur_name}</b>",
                inline_markup=models_keyboard()
            )

        # ── 📐 Size ──────────────────────────────────────────────────────
        elif text in ["📐 Size", "/size"]:
            sn, sw, sh = get_size(chat_id)
            send_message(chat_id,
                f"📐 <b>Image Size ಆಯ್ಕೆ ಮಾಡಿ:</b>\nCurrent: <b>{sn}</b> ({sw}×{sh})",
                inline_markup=sizes_keyboard()
            )

        # ── 📱 Ratio ─────────────────────────────────────────────────────
        elif text in ["📱 Ratio", "/ratio"]:
            cur     = user_ratio.get(chat_id)
            cur_txt = f"\nCurrent: <b>{cur['name']}</b>" if cur else ""
            send_message(chat_id,
                f"📱 <b>Platform Ratio ಆಯ್ಕೆ ಮಾಡಿ:</b>{cur_txt}",
                inline_markup=ratios_keyboard()
            )

        # ── 🎨 Style ─────────────────────────────────────────────────────
        elif text in ["🎨 Style", "/style"]:
            cur_key  = user_style.get(chat_id, "7")
            cur_name = STYLE_PRESETS[cur_key]["name"]
            send_message(chat_id,
                f"🎭 <b>Style Preset ಆಯ್ಕೆ ಮಾಡಿ:</b>\nCurrent: <b>{cur_name}</b>",
                inline_markup=styles_keyboard()
            )

        # ── ✨ Enhance ────────────────────────────────────────────────────
        elif text in ["✨ Enhance", "/enhance"]:
            cur     = user_enhance.get(chat_id, True)
            new_val = not cur
            user_enhance[chat_id] = new_val
            status  = "✅ ON" if new_val else "❌ OFF"
            send_message(chat_id,
                f"✨ <b>Prompt Enhancement: {status}</b>\n\n"
                + ("Pollinations AI ನಿಮ್ಮ prompt ಅನ್ನು ತಾನೇ improve ಮಾಡುತ್ತದೆ."
                   if new_val else
                   "Prompt ಯಥಾವತ್ ಉಪಯೋಗಿಸಲಾಗುತ್ತದೆ.")
            )

        # ── 📊 Stats ─────────────────────────────────────────────────────
        elif text in ["📊 Stats", "/stats"]:
            breakdown = "\n".join(
                f"  {MODELS[k]['name']}: <b>{v}</b> images"
                for k, v in stats["model_usage"].items()
            )
            send_message(chat_id,
                f"📊 <b>CC_PIC Stats:</b>\n\n"
                f"🖼️ Total Images: <b>{stats['total']}</b>\n"
                f"👥 Total Users: <b>{len(user_all_ids)}</b>\n"
                f"🕐 Since: <b>{stats['since']}</b>\n\n"
                f"🎨 <b>Model Breakdown:</b>\n{breakdown}"
            )

        # ── 🎲 Random ────────────────────────────────────────────────────
        elif text in ["🎲 Random", "/random"]:
            rp = random.choice(RANDOM_PROMPTS)
            send_message(chat_id, f"🎲 <b>Random Prompt:</b>\n<i>{rp}</i>")
            do_generate(chat_id, rp)

        # ── 🏆 Daily Challenge ───────────────────────────────────────────
        elif text in ["🏆 Daily Challenge", "/daily"]:
            day   = datetime.now().timetuple().tm_yday
            theme = DAILY_THEMES[day % len(DAILY_THEMES)]
            send_message(chat_id,
                f"🏆 <b>Today's Prompt Challenge:</b>\n\n"
                f"🎯 Theme: <b>{theme}</b>\n\n"
                f"💡 ಈ theme ಬಳಸಿ prompt type ಮಾಡಿ!\n"
                f"<i>Example: ancient Indian warrior in space, nebula, epic, 8K</i>"
            )

        # ── /upscale ─────────────────────────────────────────────────────
        elif text.startswith("/upscale"):
            last = user_last_prompt.get(chat_id)
            if last:
                do_generate(chat_id, last, upscale=True)
            else:
                send_message(chat_id, "⚠️ ಮೊದಲು ಒಂದು image generate ಮಾಡಿ.")

        # ── /broadcast (admin) ───────────────────────────────────────────
        elif text.startswith("/broadcast"):
            if ADMIN_CHAT_ID and str(chat_id) == str(ADMIN_CHAT_ID):
                msg = text[len("/broadcast"):].strip()
                if msg:
                    success = 0
                    for uid in list(user_all_ids):
                        r = send_message(uid, f"📢 <b>CC_PIC Update:</b>\n\n{msg}")
                        if r and r.get("ok"):
                            success += 1
                    send_message(chat_id, f"✅ Broadcast sent to {success}/{len(user_all_ids)} users!")
                else:
                    send_message(chat_id, "Usage: /broadcast Your message")
            else:
                send_message(chat_id, "❌ Admin only.")

        # ── /generate (backward compat) ──────────────────────────────────
        elif text.startswith("/generate"):
            prompt = text[9:].strip()
            if not prompt:
                send_message(chat_id, "⚠️ Prompt ಕೊಡಿ!\nOr just type directly — no command needed!")
            else:
                do_generate(chat_id, prompt)

        # ── /models ──────────────────────────────────────────────────────
        elif text.startswith("/models"):
            ml = "\n\n".join(
                f"{k}. <b>{v['name']}</b> — {v['desc']}" for k, v in MODELS.items()
            )
            send_message(chat_id, f"🎨 <b>Available Models:</b>\n\n{ml}")

        # ── Batch OR plain-text prompt ───────────────────────────────────
        else:
            batch = re.match(r'^(\d+)x:\s*(.+)$', text.strip(), re.IGNORECASE)
            if batch:
                count  = min(int(batch.group(1)), 4)
                prompt = batch.group(2).strip()
                send_message(chat_id,
                    f"🔁 <b>Batch: {count} images</b>\n"
                    f"📝 <i>{prompt[:100]}</i>\n"
                    f"⏳ ಒಂದೊಂದಾಗಿ generate ಮಾಡ್ತೀನಿ..."
                )
                for i in range(count):
                    send_message(chat_id, f"🎨CC_PIC <b>{i+1}/{count}</b>...")
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
        })
    return jsonify({"error": "Failed"})

@app.route('/')
def index():
    return "🎨 CC_PIC Bot v6 running! Visit /setup to configure webhook."

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
