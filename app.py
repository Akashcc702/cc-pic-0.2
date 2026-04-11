from flask import Flask, request, jsonify
import requests
import os
import logging
import urllib.parse
import time
import random

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?model={model}&width={width}&height={height}&seed={seed}&nologo=true&enhance=true"

MODELS = {
    "1": {"name": "FLUX ⚡", "id": "flux", "desc": "Best quality (Recommended)"},
    "2": {"name": "FLUX Realism 📸", "id": "flux-realism", "desc": "Photorealistic images"},
    "3": {"name": "FLUX Anime 🎌", "id": "flux-anime", "desc": "Anime style images"},
    "4": {"name": "Turbo ⚡⚡", "id": "turbo", "desc": "Fastest generation"}
}

SIZES = {
    "1": {"name": "Square 1:1", "w": 1024, "h": 1024},
    "2": {"name": "Portrait 2:3", "w": 832, "h": 1216},
    "3": {"name": "Landscape 3:2", "w": 1216, "h": 832},
    "4": {"name": "Wide 16:9", "w": 1344, "h": 768},
}

user_model_choice = {}
user_size_choice = {}

# =========================================================
# HELPERS
# =========================================================
def telegram_api(method, data=None, files=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    try:
        if files:
            response = requests.post(url, data=data, files=files, timeout=30)
        elif data:
            response = requests.post(url, json=data, timeout=30)
        else:
            response = requests.get(url, timeout=30)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        logger.error(f"Telegram API error: {str(e)}")
        return None

def generate_image(prompt, model_id, width=1024, height=1024):
    """Generate image with auto-retry on 429 rate limit"""
    seed = random.randint(1, 999999)
    encoded_prompt = urllib.parse.quote(prompt)

    url = POLLINATIONS_URL.format(
        prompt=encoded_prompt,
        model=model_id,
        width=width,
        height=height,
        seed=seed
    )
    logger.info(f"Pollinations URL: {url}")

    MAX_RETRIES = 4
    RETRY_DELAYS = [5, 10, 20, 30]  # seconds between retries

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, timeout=120)
            logger.info(f"Attempt {attempt+1} — Status: {response.status_code}")

            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '')
                if 'image' in content_type or len(response.content) > 1000:
                    return response.content, None
                else:
                    return None, "❌ Image data ಬರಲಿಲ್ಲ. ಮತ್ತೆ try ಮಾಡಿ."

            elif response.status_code == 429:
                # Rate limited — wait and retry
                wait = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else 30
                logger.warning(f"Rate limited. Waiting {wait}s before retry {attempt+1}/{MAX_RETRIES}")
                time.sleep(wait)
                continue  # retry

            else:
                return None, f"❌ Error {response.status_code}. ಮತ್ತೆ try ಮಾಡಿ."

        except requests.Timeout:
            logger.warning(f"Timeout on attempt {attempt+1}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])
                continue
            return None, "⏰ Timeout. ಮತ್ತೆ try ಮಾಡಿ."

        except Exception as e:
            logger.error(f"generate_image error: {str(e)}")
            return None, f"❌ Error: {str(e)}"

    return None, "❌ ಹಲವು ಬಾರಿ try ಮಾಡಿದರೂ ಆಗಲಿಲ್ಲ. ಕೆಲವು seconds ಕಾಯಿ ಮತ್ತೆ try ಮಾಡಿ."

def models_keyboard():
    buttons = []
    for key, model in MODELS.items():
        buttons.append([{"text": f"{model['name']} — {model['desc']}", "callback_data": f"model_{key}"}])
    return {"inline_keyboard": buttons}

def sizes_keyboard():
    buttons = []
    for key, size in SIZES.items():
        buttons.append([{"text": f"{size['name']} ({size['w']}×{size['h']})", "callback_data": f"size_{key}"}])
    return {"inline_keyboard": buttons}

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_api("sendMessage", payload)

# =========================================================
# WEBHOOK
# =========================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()

        # Inline button clicks
        if "callback_query" in data:
            callback = data["callback_query"]
            chat_id = callback["message"]["chat"]["id"]
            cb_data = callback.get("data", "")
            callback_id = callback["id"]

            if cb_data.startswith("model_"):
                key = cb_data.replace("model_", "")
                if key in MODELS:
                    user_model_choice[chat_id] = key
                    model = MODELS[key]
                    telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": f"✅ {model['name']} selected!"})
                    send_message(chat_id, f"✅ Model: <b>{model['name']}</b>\n\n💡 Now: /generate your prompt")

            elif cb_data.startswith("size_"):
                key = cb_data.replace("size_", "")
                if key in SIZES:
                    user_size_choice[chat_id] = key
                    size = SIZES[key]
                    telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": f"✅ {size['name']} selected!"})
                    send_message(chat_id, f"✅ Size: <b>{size['name']}</b> ({size['w']}×{size['h']})\n\n💡 Now: /generate your prompt")

            return jsonify({'status': 'ok'})

        # Regular messages
        message = data.get('message', {})
        chat_id = message.get('chat', {}).get('id')
        text = message.get('text', '')

        if not chat_id or not text:
            return jsonify({'status': 'ok'})

        if text.startswith('/start'):
            send_message(chat_id,
                "🤖 <b>CC Pic Bot v5 — AI Image Generator</b>\n\n"
                "⚡ Powered by Pollinations.ai\n"
                "✅ 100% Free • No limits • No credits!\n\n"
                "📌 <b>Commands:</b>\n"
                "/generate &lt;prompt&gt; — Image generate\n"
                "/model — Model ಆಯ್ಕೆ\n"
                "/size — Image size ಆಯ್ಕೆ\n"
                "/models — ಎಲ್ಲಾ models\n"
                "/help — Help\n\n"
                "🎨 <b>Example:</b>\n"
                "/generate a sunset over mountains, cinematic, 4K"
            )

        elif text.startswith('/help'):
            send_message(chat_id,
                "📖 <b>CC Pic Bot Help:</b>\n\n"
                "1️⃣ /model → Model ಆಯ್ಕೆ\n"
                "2️⃣ /size → Size ಆಯ್ಕೆ\n"
                "3️⃣ /generate your prompt → Image!\n\n"
                "💡 <b>Prompt Tips:</b>\n"
                "• <i>\"a mountain lake at sunrise, 4K, cinematic\"</i>\n"
                "• Style: <i>anime, oil painting, photorealistic</i>\n"
                "• Quality: <i>detailed, sharp, HD, 8K</i>\n\n"
                "⚠️ Rate limit ಬಂದರೆ bot ತಾನೇ retry ಮಾಡುತ್ತದೆ!\n"
                "⚡ Default: FLUX model, 1024×1024"
            )

        elif text.startswith('/models'):
            model_list = "\n\n".join([f"{k}. <b>{v['name']}</b>\n   └ {v['desc']}" for k, v in MODELS.items()])
            send_message(chat_id, f"🎨 <b>Available Models:</b>\n\n{model_list}\n\n/model ಬಳಸಿ select ಮಾಡಿ.")

        elif text.startswith('/model'):
            send_message(chat_id, "🎨 <b>Model ಆಯ್ಕೆ ಮಾಡಿ:</b>", reply_markup=models_keyboard())

        elif text.startswith('/size'):
            send_message(chat_id, "📐 <b>Image Size ಆಯ್ಕೆ ಮಾಡಿ:</b>", reply_markup=sizes_keyboard())

        elif text.startswith('/generate'):
            prompt = text.replace('/generate', '', 1).strip()
            if not prompt:
                send_message(chat_id, "⚠️ Prompt ಕೊಡಿ!\n\n<b>Example:</b> /generate a beautiful mountain landscape")
                return jsonify({'status': 'ok'})

            model_key = user_model_choice.get(chat_id, "1")
            size_key = user_size_choice.get(chat_id, "1")
            model = MODELS[model_key]
            size = SIZES[size_key]

            send_message(chat_id,
                f"🎨 <b>{model['name']}</b> | 📐 {size['name']}\n"
                f"📝 <i>{prompt[:100]}</i>\n\n"
                f"⏳ Generate ಆಗ್ತಿದೆ..."
            )

            image_data, error = generate_image(prompt, model["id"], size["w"], size["h"])

            if image_data:
                files = {'photo': ('image.jpg', image_data, 'image/jpeg')}
                result = telegram_api("sendPhoto", {
                    "chat_id": chat_id,
                    "caption": f"✅ <b>{model['name']}</b> | {size['name']}\n📝 {prompt[:200]}",
                    "parse_mode": "HTML"
                }, files=files)
                if not result or not result.get('ok'):
                    files2 = {'document': ('image.jpg', image_data, 'image/jpeg')}
                    telegram_api("sendDocument", {"chat_id": chat_id}, files=files2)
            else:
                send_message(chat_id, error or "❌ Image generate ಆಗಲಿಲ್ಲ.")

        else:
            send_message(chat_id, "👋 /generate &lt;prompt&gt; ಉಪಯೋಗಿಸಿ!\n/help ನೋಡಿ.")

        return jsonify({'status': 'ok'})

    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({'status': 'error'}), 500

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
            "webhook_url": info.get('url'),
            "pending_updates": info.get('pending_update_count'),
            "last_error": info.get('last_error_message'),
            "provider": "Pollinations.ai (Free)",
            "bot_token_set": bool(TELEGRAM_BOT_TOKEN)
        })
    return jsonify({"error": "Failed"})

@app.route('/')
def index():
    return "🤖 CC Pic Bot v5.1 running! Visit /setup to configure webhook."

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
