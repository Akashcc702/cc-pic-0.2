import os
import io
import base64
import random
import asyncio
import requests
import urllib.parse
import concurrent.futures
from datetime import datetime, timedelta

from openai import OpenAI
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)
from flask import Flask
from threading import Thread

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    MPL_OK = True
except ImportError:
    MPL_OK = False

# ════════════════════════════════════════════════
#  WEB SERVER  (Render keep-alive)
# ════════════════════════════════════════════════

app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "CC AI Bot v3.2 Running 🚀"

def _run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=_run_web, daemon=True).start()

# ════════════════════════════════════════════════
#  API KEYS
# ════════════════════════════════════════════════

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
BOT_TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID           = int(os.getenv("ADMIN_ID", "0"))

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Thread pool for blocking AI calls
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)

# ════════════════════════════════════════════════
#  MODEL CHAINS
# ════════════════════════════════════════════════

MODELS = {
    "general": [
        "google/gemma-3-4b-it:free",
        "meta-llama/llama-3.2-3b-instruct:free",
        "openrouter/auto",
    ],
    "coding": [
        "qwen/qwen-2.5-coder-32b-instruct:free",
        "qwen/qwen-2.5-coder-7b-instruct:free",
        "openrouter/auto",
    ],
    "research": [
        "perplexity/llama-3.1-sonar-small-128k-online",
        "google/gemini-2.5-flash-preview:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "openrouter/auto",
    ],
    "vision": [
        "qwen/qwen2.5-vl-7b-instruct:free",
        "meta-llama/llama-3.2-11b-vision-instruct:free",
        "google/gemini-2.0-flash-exp:free",
        "openrouter/auto",
    ],
}

# ════════════════════════════════════════════════
#  SYSTEM PROMPTS
# ════════════════════════════════════════════════

SYSTEM_PROMPTS = {
    "general": (
        "You are CC AI, a helpful, friendly, and intelligent assistant. "
        "Respond clearly and concisely."
    ),
    "coding": (
        "You are CC Coding AI — an expert software engineer powered by Qwen Coder.\n"
        "Specialise in: code generation, bug fixing, auto-completion, website/app creation.\n"
        "Always produce clean, well-commented, production-ready code with markdown code blocks."
    ),
    "research": (
        "You are CC Research AI — a deep search and research specialist.\n"
        "Specialise in: internet research, latest news, article summaries, fact-checking, "
        "market research, and competitor analysis.\n"
        "Provide comprehensive, well-structured, accurate information with numbered lists and sections."
    ),
    "meme": (
        "You are a viral meme caption generator. Given a topic, return ONLY:\n"
        "TOP: <top text>\nBOTTOM: <bottom text>\n\n"
        "Keep each line under 8 words. Make it funny, relatable, and internet-style. "
        "No explanation, no extra text — just those two lines."
    ),
    "avatar_desc": (
        "Describe the person in this image for a 3D avatar prompt. "
        "List only physical features: gender, approximate age, hair color/style, "
        "skin tone, notable features. Keep it under 20 words. No sentences — just descriptors."
    ),
}

# ════════════════════════════════════════════════
#  BUTTON LABELS
# ════════════════════════════════════════════════

# ── Main menu ──
BTN_CODING   = "💻 Coding"
BTN_RESEARCH = "🔍 Research"
BTN_IMAGEGEN = "🎨 Image Gen"
BTN_GENERAL  = "🤖 General AI"
BTN_HELP     = "ℹ️ Help"
BTN_RESET    = "🔄 Reset"

# ── Coding sub ──
BTN_CODEGEN  = "⚡ Code Generate"
BTN_BUGFIX   = "🐛 Bug Fixing"
BTN_AUTOCMP  = "✨ Auto Complete"
BTN_WEBAPP   = "🌐 Website / App"

# ── Research sub ──
BTN_INTERNET = "🌐 Internet Research"
BTN_NEWS     = "📰 Latest News"
BTN_SUMMARY  = "📄 Article Summary"
BTN_FACT     = "✅ Fact Checking"
BTN_MARKET   = "📊 Market Research"
BTN_COMPETE  = "🏢 Competitor Analysis"

# ── Image gen sub ──
BTN_T2I       = "🖼️ Text → Image"
BTN_LOGO      = "🎯 Logo Design"
BTN_POSTER    = "📢 Poster / Banner"
BTN_ANIME     = "🎭 Anime / Art"
BTN_CINEMATIC = "🎬 Cinematic"
BTN_MEME      = "😂 Meme Creator"

# ── Common ──
BTN_BACK = "🔙 Main Menu"

NAV_BUTTONS = {
    BTN_CODING, BTN_RESEARCH, BTN_IMAGEGEN, BTN_GENERAL,
    BTN_HELP, BTN_RESET, BTN_CODEGEN, BTN_BUGFIX, BTN_AUTOCMP,
    BTN_WEBAPP, BTN_INTERNET, BTN_NEWS, BTN_SUMMARY, BTN_FACT,
    BTN_MARKET, BTN_COMPETE, BTN_T2I, BTN_LOGO, BTN_POSTER,
    BTN_ANIME, BTN_CINEMATIC, BTN_MEME, BTN_BACK,
}

# ════════════════════════════════════════════════
#  KEYBOARDS
# ════════════════════════════════════════════════

def main_kb():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_CODING),   KeyboardButton(BTN_RESEARCH)],
            [KeyboardButton(BTN_IMAGEGEN), KeyboardButton(BTN_GENERAL)],
            [KeyboardButton(BTN_HELP),     KeyboardButton(BTN_RESET)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )

def coding_kb():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_CODEGEN), KeyboardButton(BTN_BUGFIX)],
            [KeyboardButton(BTN_AUTOCMP), KeyboardButton(BTN_WEBAPP)],
            [KeyboardButton(BTN_BACK)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )

def research_kb():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_INTERNET), KeyboardButton(BTN_NEWS)],
            [KeyboardButton(BTN_SUMMARY),  KeyboardButton(BTN_FACT)],
            [KeyboardButton(BTN_MARKET),   KeyboardButton(BTN_COMPETE)],
            [KeyboardButton(BTN_BACK)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )

def imagegen_kb():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_T2I),       KeyboardButton(BTN_CINEMATIC)],
            [KeyboardButton(BTN_LOGO),      KeyboardButton(BTN_POSTER)],
            [KeyboardButton(BTN_ANIME),     KeyboardButton(BTN_MEME)],
            [KeyboardButton(BTN_BACK)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )

# ════════════════════════════════════════════════
#  USER STATE
# ════════════════════════════════════════════════

user_memory:  dict = {}
user_mode:    dict = {}
user_submode: dict = {}
all_users:    set  = set()
user_stats:   dict = {}

ACTIVE_MINUTES = 5

def get_mode(uid): return user_mode.get(uid, "general")
def get_sub(uid):  return user_submode.get(uid, "")

def register_user(uid, update=None):
    all_users.add(uid)
    now = datetime.now()
    if uid not in user_stats:
        user_stats[uid] = {
            "name":        "",
            "username":    "",
            "chat_count":  0,
            "first_seen":  now,
            "last_active": now,
        }
    if update and update.message and update.message.from_user:
        fu = update.message.from_user
        user_stats[uid]["name"]     = fu.first_name or fu.username or str(uid)
        user_stats[uid]["username"] = f"@{fu.username}" if fu.username else ""
    user_stats[uid]["last_active"] = now

def bump_chat(uid):
    if uid in user_stats:
        user_stats[uid]["chat_count"]  += 1
        user_stats[uid]["last_active"]  = datetime.now()

# ════════════════════════════════════════════════
#  ✨ FEATURE 3 — LIVE TYPING ANIMATION
# ════════════════════════════════════════════════

async def _anim_loop(msg, prefix):
    """Background coroutine: animates dots until cancelled."""
    frames = [
        f"{prefix}\n⬜⬜⬜⬜⬜⬜⬜⬜",
        f"{prefix}\n🟦⬜⬜⬜⬜⬜⬜⬜",
        f"{prefix}\n🟦🟦⬜⬜⬜⬜⬜⬜",
        f"{prefix}\n🟦🟦🟦⬜⬜⬜⬜⬜",
        f"{prefix}\n🟦🟦🟦🟦⬜⬜⬜⬜",
        f"{prefix}\n🟦🟦🟦🟦🟦⬜⬜⬜",
        f"{prefix}\n🟦🟦🟦🟦🟦🟦⬜⬜",
        f"{prefix}\n🟦🟦🟦🟦🟦🟦🟦⬜",
        f"{prefix}\n🟦🟦🟦🟦🟦🟦🟦🟦",
    ]
    i = 0
    while True:
        try:
            await msg.edit_text(frames[i % len(frames)])
            await asyncio.sleep(0.45)
            i += 1
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(0.45)

async def run_with_typing(update, prefix, fn, *args):
    """
    Run blocking fn(*args) in thread executor while showing
    animated typing indicator. Returns fn result.
    """
    msg  = await update.message.reply_text(f"{prefix}\n⬜⬜⬜⬜⬜⬜⬜⬜")
    task = asyncio.create_task(_anim_loop(msg, prefix))
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(_executor, fn, *args)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return msg, result

# ════════════════════════════════════════════════
#  ✨ FEATURE 4 — ANIMATED PROGRESS BAR
# ════════════════════════════════════════════════

_RESEARCH_STEPS = [
    ("🔍 Searching the web...",    "[██░░░░░░]", 25),
    ("📡 Fetching sources...",     "[████░░░░]", 50),
    ("📊 Analysing results...",    "[██████░░]", 75),
    ("✍️  Writing response...",    "[███████░]", 90),
]

_CODING_STEPS = [
    ("🧠 Understanding task...",   "[██░░░░░░]", 25),
    ("⚙️  Designing solution...",  "[████░░░░]", 50),
    ("💻 Writing code...",         "[██████░░]", 75),
    ("🔍 Reviewing output...",     "[███████░]", 90),
]

_IMAGE_STEPS = [
    ("🎨 Crafting your prompt...", "[██░░░░░░]", 25),
    ("🖌️  Generating image...",    "[████░░░░]", 50),
    ("✨ Adding details...",       "[██████░░]", 75),
    ("📸 Finalising...",           "[███████░]", 90),
]

async def progress_bar_run(update, steps, fn, *args):
    """
    Show step-by-step animated progress while running fn in executor.
    Returns (status_msg, result).
    """
    msg  = await update.message.reply_text(f"{steps[0][0]}\n{steps[0][1]} {steps[0][2]}%")
    loop = asyncio.get_event_loop()

    async def _progress():
        for label, bar, pct in steps[1:]:
            await asyncio.sleep(1.8)
            try:
                await msg.edit_text(f"{label}\n{bar} {pct}%")
            except Exception:
                pass

    prog_task = asyncio.create_task(_progress())
    try:
        result = await loop.run_in_executor(_executor, fn, *args)
    finally:
        prog_task.cancel()
        try:
            await prog_task
        except asyncio.CancelledError:
            pass

    try:
        await msg.edit_text("✅ Done!\n[████████] 100%")
        await asyncio.sleep(0.4)
    except Exception:
        pass

    return msg, result

# ════════════════════════════════════════════════
#  AI HELPERS
# ════════════════════════════════════════════════

def call_ai(messages, mode="general"):
    chain = MODELS.get(mode, MODELS["general"])
    last_err = "Unknown error"
    for model in chain:
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, max_tokens=2048,
            )
            return resp.choices[0].message.content
        except Exception as e:
            last_err = str(e)
    return f"⚠️ All AI models failed.\nError: {last_err}"


def call_vision_ai(image_b64, mime, user_text):
    question = user_text or "Analyse this image in detail. Describe everything you see."
    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            {"type": "text", "text": question},
        ],
    }]
    for model in MODELS["vision"]:
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, max_tokens=512,
            )
            return resp.choices[0].message.content
        except Exception:
            continue
    return "⚠️ Vision AI unavailable."


# ── Pollinations.ai ──
_POLL_URL = (
    "https://image.pollinations.ai/prompt/{prompt}"
    "?width=1024&height=1024&model=flux&seed={seed}&nologo=true&enhance=true"
)

_CINEMATIC_PREFIX = (
    "cinematic 3D render, octane renderer, cinema4d, photorealistic, "
    "dramatic studio lighting, subsurface scattering, ray tracing, 8K ultra HD, "
    "depth of field, volumetric fog, professional color grading,"
)

_IMG_STYLE = {
    BTN_T2I:       _CINEMATIC_PREFIX,   # Text → Image: cinematic quality
    BTN_LOGO:      "professional minimal vector logo, clean white background, bold typography, flat design,",
    BTN_POSTER:    "high-quality poster design, vibrant colors, bold layout, professional graphic design,",
    BTN_ANIME:     "anime illustration, highly detailed, studio-quality, vibrant colors, sharp linework,",
    BTN_CINEMATIC: _CINEMATIC_PREFIX,   # Cinematic: same style (text→render or photo→avatar)
}

def make_image(prompt, submode):
    style   = _IMG_STYLE.get(submode, "")
    full    = f"{style} {prompt}".strip() if style else prompt
    encoded = urllib.parse.quote(full)
    seed    = random.randint(1, 999_999)
    return _POLL_URL.format(prompt=encoded, seed=seed)


# ── Prompt prefixes ──
_RESEARCH_PREFIX = {
    BTN_INTERNET: "Conduct thorough research and provide a detailed answer for: ",
    BTN_NEWS:     "Find and summarise the LATEST news about: ",
    BTN_SUMMARY:  "Provide a comprehensive and structured summary of: ",
    BTN_FACT:     "Fact-check the following step by step, citing evidence: ",
    BTN_MARKET:   "Provide detailed market research analysis including size, trends, key players for: ",
    BTN_COMPETE:  "Conduct a thorough competitor analysis including strengths, weaknesses, strategy for: ",
}
_CODING_PREFIX = {
    BTN_CODEGEN: "Generate complete, well-commented, production-ready code for: ",
    BTN_BUGFIX:  "Debug and fix the following code or error (explain issue + provide fix): ",
    BTN_AUTOCMP: "Complete and improve the following code snippet (explain additions): ",
    BTN_WEBAPP:  "Create a complete, working website/app with full code for: ",
}

def build_input(raw, mode, sub):
    if mode == "research":
        p = _RESEARCH_PREFIX.get(sub, "")
        return f"{p}{raw}" if p else raw
    if mode == "coding":
        p = _CODING_PREFIX.get(sub, "")
        return f"{p}{raw}" if p else raw
    return raw


# ════════════════════════════════════════════════
#  ✨ FEATURE 6 — ANIMATED MEME CREATOR
# ════════════════════════════════════════════════

def _get_font(size=48):
    """Return a PIL font — tries bold system fonts, falls back to default."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _draw_meme_text(draw, img_w, img_h, top_text, bottom_text, font):
    """Draw white text with black outline on image."""
    def draw_outlined(text, y, anchor="mt"):
        offsets = [(-2,-2),(2,-2),(-2,2),(2,2),(0,-2),(0,2),(-2,0),(2,0)]
        x = img_w // 2
        for ox, oy in offsets:
            draw.text((x+ox, y+oy), text, font=font, fill="black", anchor=anchor)
        draw.text((x, y), text, font=font, fill="white", anchor=anchor)

    if top_text:
        draw_outlined(top_text.upper(), 14, anchor="mt")
    if bottom_text:
        draw_outlined(bottom_text.upper(), img_h - 14, anchor="mb")


def make_meme_gif(image_bytes, top_text, bottom_text):
    """
    Create animated shake-effect meme GIF.
    Returns gif bytes or None on failure.
    """
    if not PIL_OK:
        return None
    try:
        base = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        base = base.resize((512, 512), Image.LANCZOS)
        font = _get_font(46)

        # Shake offsets for 6 frames
        shakes = [(0,0),(3,-2),(-3,2),(2,3),(-2,-3),(0,0)]
        frames = []

        for ox, oy in shakes:
            frame = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
            frame.paste(base, (ox, oy))
            draw  = ImageDraw.Draw(frame)
            _draw_meme_text(draw, 512, 512, top_text, bottom_text, font)
            frames.append(frame.convert("P", palette=Image.ADAPTIVE, dither=0))

        buf = io.BytesIO()
        frames[0].save(
            buf, format="GIF",
            save_all=True,
            append_images=frames[1:],
            loop=0,
            duration=110,
            disposal=2,
        )
        return buf.getvalue()
    except Exception as e:
        print(f"Meme GIF error: {e}")
        return None


def _ai_meme_caption(topic):
    """Ask AI to generate top/bottom meme text for a topic."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPTS["meme"]},
        {"role": "user",   "content": topic},
    ]
    raw = call_ai(messages, "general")
    top = bottom = ""
    for line in raw.splitlines():
        l = line.strip()
        if l.upper().startswith("TOP:"):
            top = l[4:].strip()
        elif l.upper().startswith("BOTTOM:"):
            bottom = l[7:].strip()
    if not top and not bottom:
        top    = raw[:40].strip()
        bottom = "lol"
    return top, bottom


# ════════════════════════════════════════════════
#  ✨ FEATURE 5 — ANIMATED GROWTH CHART
# ════════════════════════════════════════════════

def make_growth_chart():
    """
    Build a styled bar chart of daily new users.
    Returns PNG bytes or None.
    """
    if not MPL_OK:
        return None

    # Aggregate first_seen dates
    day_counts: dict = {}
    for s in user_stats.values():
        d = s.get("first_seen")
        if d:
            key = d.strftime("%d %b")
            day_counts[key] = day_counts.get(key, 0) + 1

    if not day_counts:
        # Demo data so chart isn't empty
        today = datetime.now()
        for i in range(7):
            d = (today - timedelta(days=6-i)).strftime("%d %b")
            day_counts[d] = random.randint(1, 12)

    labels = list(day_counts.keys())[-14:]   # last 14 days
    values = [day_counts[l] for l in labels]
    cumulative = []
    total = 0
    for v in values:
        total += v
        cumulative.append(total)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6),
                                   facecolor="#0d1117", gridspec_kw={"hspace": 0.45})

    # ── Top: Daily new users (bar) ──
    colors = ["#58a6ff" if v == max(values) else "#1f6feb" for v in values]
    bars = ax1.bar(labels, values, color=colors, edgecolor="none", zorder=3)
    ax1.set_facecolor("#0d1117")
    ax1.set_title("📊 Daily New Users", color="#c9d1d9", fontsize=12, pad=8)
    ax1.tick_params(axis="x", colors="#8b949e", labelsize=8, rotation=30)
    ax1.tick_params(axis="y", colors="#8b949e", labelsize=8)
    ax1.spines[:].set_visible(False)
    ax1.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax1.set_ylim(0, max(values) * 1.25 + 1)
    ax1.grid(axis="y", color="#21262d", zorder=0, linewidth=0.7)
    for bar, v in zip(bars, values):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                 str(v), ha="center", va="bottom", fontsize=8, color="#c9d1d9")

    # ── Bottom: Cumulative growth (line) ──
    ax2.plot(labels, cumulative, color="#3fb950", linewidth=2.2,
             marker="o", markersize=4, markerfacecolor="#3fb950", zorder=3)
    ax2.fill_between(labels, cumulative, alpha=0.15, color="#3fb950", zorder=2)
    ax2.set_facecolor("#0d1117")
    ax2.set_title("📈 Total Users (Cumulative)", color="#c9d1d9", fontsize=12, pad=8)
    ax2.tick_params(axis="x", colors="#8b949e", labelsize=8, rotation=30)
    ax2.tick_params(axis="y", colors="#8b949e", labelsize=8)
    ax2.spines[:].set_visible(False)
    ax2.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax2.grid(axis="y", color="#21262d", zorder=0, linewidth=0.7)
    for x, y in zip(labels[::2], cumulative[::2]):
        ax2.text(x, y + 0.3, str(y), ha="center", va="bottom",
                 fontsize=7.5, color="#8b949e")

    fig.text(0.5, 0.01, f"CC AI Bot  •  Generated {datetime.now().strftime('%d %b %Y %H:%M')}",
             ha="center", fontsize=7.5, color="#484f58")

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor="#0d1117")
    plt.close(fig)
    return buf.getvalue()


# ════════════════════════════════════════════════
#  COMMANDS
# ════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    register_user(uid, update)
    user_mode[uid]    = "general"
    user_memory[uid]  = []
    user_submode[uid] = ""
    await update.message.reply_text(
        "🤖 *Hello! I am CC AI Bot.*\n"
        "Ask me anything.\n\n"
        "What I can do:\n"
        "💻 *Coding* — generate, debug & complete code\n"
        "🔍 *Research* — deep search & internet research\n"
        "🎨 *Image Gen* — cinematic renders, avatars, memes & more\n"
        "📷 *Vision* — send any photo to analyse it!\n\n"
        "Choose a mode from the buttons below 👇",
        parse_mode="Markdown",
        reply_markup=main_kb(),
    )

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    register_user(uid, update)
    user_memory[uid]  = []
    user_mode[uid]    = "general"
    user_submode[uid] = ""
    await update.message.reply_text("🔄 Memory cleared! Back to General AI.", reply_markup=main_kb())

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.message.chat_id, update)
    await update.message.reply_text(
        "📖 *CC AI Bot v3.2 — Help*\n\n"
        "*Commands:*\n"
        "/start — Welcome screen\n"
        "/reset — Clear memory & mode\n"
        "/help  — This message\n\n"
        "*Modes (buttons):*\n"
        "💻 Coding   → CC Coder 2.5 32B\n"
        "🔍 Research → CC AI Deep Search 2.3 64B\n"
        "🎨 Image Gen → CC PIC 2.5 Flash\n"
        "🤖 General  → CC AI 1.2 4B\n\n"
        "*Image Gen sub-modes:*\n"
        "🖼️ Text → Image — cinematic quality from prompt\n"
        "🎬 Cinematic — text prompt for 3D render  |  photo for avatar\n"
        "🎯 Logo — professional brand logos\n"
        "📢 Poster/Banner — bold promotional visuals\n"
        "🎭 Anime/Art — illustrated creations\n"
        "😂 Meme — AI-captioned animated GIF\n\n"
        "📷 *Vision:* send any photo!\n\n"
        "🔐 *Admin:* /message /users /status /chart",
        parse_mode="Markdown",
        reply_markup=main_kb(),
    )

# ════════════════════════════════════════════════
#  ADMIN COMMANDS
# ════════════════════════════════════════════════

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    if uid != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorised.")
        return
    text = " ".join(context.args).strip() if context.args else ""
    if not text:
        await update.message.reply_text("⚠️ *Usage:* `/message Your text`", parse_mode="Markdown")
        return
    if not all_users:
        await update.message.reply_text("ℹ️ No users yet.")
        return
    broadcast_text = (
        f"📢 *Message from Admin*\n"
        f"━━━━━━━━━━━━━━━━━━━\n{text}\n"
        f"━━━━━━━━━━━━━━━━━━━\n_— CC AI Bot_"
    )
    status_msg = await update.message.reply_text(f"📤 Broadcasting to {len(all_users)} users…")
    success, failed, blocked = 0, 0, []
    for u in list(all_users):
        try:
            await context.bot.send_message(chat_id=u, text=broadcast_text, parse_mode="Markdown")
            success += 1
        except Exception as e:
            failed += 1
            if any(x in str(e).lower() for x in ["blocked","deactivated","forbidden"]):
                blocked.append(u)
    for b in blocked:
        all_users.discard(b)
    await status_msg.edit_text(
        f"✅ *Broadcast Done!*\n\n📨 Sent: {success}\n❌ Failed: {failed}\n"
        f"🚫 Blocked: {len(blocked)} (removed)\n👥 Active: {len(all_users)}",
        parse_mode="Markdown",
    )

async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorised.")
        return
    await update.message.reply_text(f"👥 *Total Users:* {len(all_users)}", parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    if uid != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorised.")
        return
    now    = datetime.now()
    cutoff = now - timedelta(minutes=ACTIVE_MINUTES)
    total  = len(all_users)
    active = [u for u in all_users if user_stats.get(u,{}).get("last_active",datetime.min) >= cutoff]

    sorted_users = sorted(
        user_stats.items(),
        key=lambda x: x[1].get("last_active", datetime.min),
        reverse=True,
    )[:30]

    lines = []
    for i, (u, s) in enumerate(sorted_users, 1):
        name  = s.get("name","") or str(u)
        uname = s.get("username","")
        chats = s.get("chat_count", 0)
        la    = s.get("last_active", datetime.min)
        fs    = s.get("first_seen",  datetime.min)
        la_str = la.strftime("%d/%m %H:%M") if la != datetime.min else "—"
        fs_str = fs.strftime("%d/%m/%y")    if fs != datetime.min else "—"
        dot   = "🟢" if la >= cutoff else "⚫"
        display = uname if uname else f"ID:{u}"
        lines.append(f"{dot} {i}. {name} ({display})\n   💬 {chats} | 🕐 {la_str} | 📅 {fs_str}")

    user_list = "\n".join(lines) if lines else "_No data yet_"
    msg = (
        f"📊 *CC AI Bot — Status*\n━━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Total:* {total}\n🟢 *Active Now:* {len(active)}\n"
        f"━━━━━━━━━━━━━━━━━━━\n*Recent Users (30):*\n\n{user_list}\n"
        f"━━━━━━━━━━━━━━━━━━━\n_Updated: {now.strftime('%d/%m/%Y %H:%M:%S')}_"
    )
    for chunk in [msg[i:i+4096] for i in range(0, len(msg), 4096)]:
        await update.message.reply_text(chunk, parse_mode="Markdown")


# ✨ FEATURE 5 — /chart command
async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    if uid != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorised.")
        return

    msg, png = await run_with_typing(update, "📈 Generating growth chart...", make_growth_chart)
    await msg.delete()

    if png:
        await update.message.reply_photo(
            photo=png,
            caption=(
                f"📊 *CC AI Bot — Growth Chart*\n"
                f"👥 Total users: *{len(all_users)}*\n"
                f"_Generated {datetime.now().strftime('%d %b %Y %H:%M')}_"
            ),
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("⚠️ matplotlib not available. Run: `pip install matplotlib`")

# ════════════════════════════════════════════════
#  TEXT HANDLER
# ════════════════════════════════════════════════

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.message.chat_id
    text = update.message.text.strip()
    register_user(uid, update)

    if uid not in user_memory:
        user_memory[uid] = []

    # ════ NAVIGATION ════════════════════════════

    if text == BTN_BACK:
        user_mode[uid] = "general"; user_submode[uid] = ""
        await update.message.reply_text("🏠 Back to main menu.", reply_markup=main_kb())
        return

    if text == BTN_RESET:
        user_memory[uid] = []; user_mode[uid] = "general"; user_submode[uid] = ""
        await update.message.reply_text("🔄 Memory cleared!", reply_markup=main_kb())
        return

    if text == BTN_HELP:
        await update.message.reply_text(
            "📖 Use buttons to switch modes.\n\n"
            "💻 Coding  🔍 Research  🎨 Image Gen  🤖 General\n"
            "🎬 Cinematic  😂 Meme Creator\n\n"
            "📷 Send any photo for Vision AI analysis!",
            reply_markup=main_kb(),
        )
        return

    # ── Mode switches ──
    if text == BTN_CODING:
        user_mode[uid] = "coding"; user_submode[uid] = ""
        await update.message.reply_text(
            "💻 *Coding AI Mode*\nPowered by CC Coder 2.5 32B.\nChoose a task 👇",
            parse_mode="Markdown", reply_markup=coding_kb())
        return

    if text == BTN_RESEARCH:
        user_mode[uid] = "research"; user_submode[uid] = ""
        await update.message.reply_text(
            "🔍 *Research AI Mode*\nCC AI Deep Search 2.3 64B.\nChoose a type 👇",
            parse_mode="Markdown", reply_markup=research_kb())
        return

    if text == BTN_IMAGEGEN:
        user_mode[uid] = "image_gen"; user_submode[uid] = ""
        await update.message.reply_text(
            "🎨 *Image Generation Mode*\nPowered by CC PIC 2.5 Flash\n\n"
            "🖼️ *Text → Image* — Type a prompt. Generates a cinematic-quality image.\n"
            "🎬 *Cinematic* — Type a prompt for a cinematic render, or upload a photo for a 3D avatar.\n"
            "🎯 *Logo Design* — Professional brand logos from your description.\n"
            "📢 *Poster / Banner* — Bold promotional visuals from text.\n"
            "🎭 *Anime / Art* — Illustrated and artistic creations.\n"
            "😂 *Meme Creator* — AI-captioned animated meme GIFs.\n\n"
            "Select a style below 👇",
            parse_mode="Markdown", reply_markup=imagegen_kb())
        return

    if text == BTN_GENERAL:
        user_mode[uid] = "general"; user_submode[uid] = ""
        await update.message.reply_text(
            "🤖 *General AI Mode*\nPowered by CC AI 1.2 4B.\nAsk me anything!",
            parse_mode="Markdown", reply_markup=main_kb())
        return

    # ── Sub-mode selections ──
    if text in (BTN_CODEGEN, BTN_BUGFIX, BTN_AUTOCMP, BTN_WEBAPP):
        user_submode[uid] = text
        await update.message.reply_text(f"✅ *{text}* ready!\nType your request 👇", parse_mode="Markdown")
        return

    if text in (BTN_INTERNET, BTN_NEWS, BTN_SUMMARY, BTN_FACT, BTN_MARKET, BTN_COMPETE):
        user_submode[uid] = text
        await update.message.reply_text(f"✅ *{text}* ready!\nType your request 👇", parse_mode="Markdown")
        return

    if text in (BTN_T2I, BTN_LOGO, BTN_POSTER, BTN_ANIME):
        user_submode[uid] = text
        if text == BTN_T2I:
            await update.message.reply_text(
                "🖼️ *Text → Image*\n\n"
                "Generate any image from your text prompt.\n"
                "Rendered in cinematic quality — photorealistic, studio-lit, 8K detail.\n\n"
                "Type your prompt below 👇",
                parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"✅ *{text}* is ready.\nDescribe what you want to generate 👇",
                parse_mode="Markdown")
        return

    if text == BTN_CINEMATIC:
        user_submode[uid] = BTN_CINEMATIC
        await update.message.reply_text(
            "🎬 *Cinematic*\n\n"
            "Two powerful generation modes in one:\n\n"
            "▸ *Text → Cinematic Render*\n"
            "  Type any prompt to generate a photorealistic,\n"
            "  cinema-grade 3D rendered image.\n\n"
            "▸ *Image Upload → Cinematic Avatar*\n"
            "  Upload your photo to receive a high-quality\n"
            "  Pixar-style 3D character avatar.\n\n"
            "Type a prompt or upload a photo to begin 👇",
            parse_mode="Markdown")
        return

    if text == BTN_MEME:
        user_submode[uid] = BTN_MEME
        await update.message.reply_text(
            "😂 *Meme Creator*\n\n"
            "Type your meme idea! Examples:\n"
            "• `coding bugs at 3am`\n"
            "• `monday morning meetings`\n"
            "• `AI taking over jobs`",
            parse_mode="Markdown")
        return

    # ════ REAL AI INPUT ═════════════════════════

    mode = get_mode(uid)
    sub  = get_sub(uid)
    bump_chat(uid)

    # ─── IMAGE GENERATION ───────────────────────
    if mode == "image_gen":

        # ✨ FEATURE 6 — Meme creator
        if sub == BTN_MEME:
            def _meme_work():
                top, bot = _ai_meme_caption(text)
                img_prompt = f"funny meme image, internet humor, {text}, no text, white background"
                encoded    = urllib.parse.quote(img_prompt)
                seed       = random.randint(1, 999_999)
                url        = _POLL_URL.format(prompt=encoded, seed=seed)
                resp       = requests.get(url, timeout=90)
                if resp.status_code != 200:
                    return None, top, bot
                gif = make_meme_gif(resp.content, top, bot)
                return gif, top, bot

            msg, (gif, top, bot) = await run_with_typing(
                update, "😂 Creating your meme...", _meme_work)
            await msg.delete()

            caption = f"😂 *Meme created!*\n⬆️ _{top}_\n⬇️ _{bot}_"
            if gif:
                await update.message.reply_animation(
                    animation=gif, caption=caption, parse_mode="Markdown")
            else:
                await update.message.reply_text(
                    "⚠️ Install Pillow for animated memes: `pip install Pillow`",
                    parse_mode="Markdown")
            return

        # Regular image gen with progress bar
        def _img_work():
            url  = make_image(text, sub)
            resp = requests.get(url, timeout=90)
            return (resp.content if resp.status_code == 200 else None, url)

        status_msg, (img_bytes, img_url) = await progress_bar_run(
            update, _IMAGE_STEPS, _img_work)
        await status_msg.delete()

        if img_bytes:
            lbl = sub.split(" ", 1)[-1] if sub else "Image"
            await update.message.reply_photo(
                photo=img_bytes,
                caption=f"🎨 *{lbl} Generated!*\n📝 _{text[:200]}_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"🖼️ [View Image]({img_url})\n_(tap to open)_",
                parse_mode="Markdown")
        return

    # ─── RESEARCH with progress bar ─────────────
    if mode == "research":
        enhanced = build_input(text, mode, sub)
        messages = (
            [{"role": "system", "content": SYSTEM_PROMPTS["research"]}]
            + user_memory[uid]
            + [{"role": "user", "content": enhanced}]
        )
        def _research():
            return call_ai(messages, "research")

        status_msg, ai_reply = await progress_bar_run(update, _RESEARCH_STEPS, _research)
        await status_msg.delete()

    # ─── CODING with typing animation ───────────
    elif mode == "coding":
        enhanced = build_input(text, mode, sub)
        messages = (
            [{"role": "system", "content": SYSTEM_PROMPTS["coding"]}]
            + user_memory[uid]
            + [{"role": "user", "content": enhanced}]
        )
        def _coding():
            return call_ai(messages, "coding")

        status_msg, ai_reply = await progress_bar_run(update, _CODING_STEPS, _coding)
        await status_msg.delete()

    # ─── GENERAL with typing animation ──────────
    else:
        messages = (
            [{"role": "system", "content": SYSTEM_PROMPTS["general"]}]
            + user_memory[uid]
            + [{"role": "user", "content": text}]
        )
        def _general():
            return call_ai(messages, "general")

        status_msg, ai_reply = await run_with_typing(update, "🤖 Thinking...", _general)
        await status_msg.delete()

    # Update memory
    user_memory[uid].append({"role": "user",      "content": text})
    user_memory[uid].append({"role": "assistant",  "content": ai_reply})
    if len(user_memory[uid]) > 20:
        user_memory[uid] = user_memory[uid][-20:]

    for chunk in [ai_reply[i:i+4096] for i in range(0, len(ai_reply), 4096)]:
        await update.message.reply_text(chunk)

# ════════════════════════════════════════════════
#  PHOTO HANDLER — Vision + Cinematic Avatar
# ════════════════════════════════════════════════

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid     = update.message.chat_id
    caption = update.message.caption or ""
    register_user(uid, update)
    bump_chat(uid)

    mode = get_mode(uid)
    sub  = get_sub(uid)

    # ── Cinematic mode: photo → Cinematic Avatar ──
    if mode == "image_gen" and sub == BTN_CINEMATIC:
        await _handle_avatar(update, context, uid, caption)
        return

    # ── Text→Image mode: photo → generate based on user prompt ──
    if mode == "image_gen" and sub == BTN_T2I:
        await _handle_t2i_photo(update, context, uid, caption)
        return

    # Standard Vision AI
    status = await update.message.reply_text("📷 Analysing your image...\n⬜⬜⬜⬜⬜⬜⬜⬜")

    try:
        photo      = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        raw_bytes  = await photo_file.download_as_bytearray()
        b64        = base64.b64encode(bytes(raw_bytes)).decode("utf-8")

        loop   = asyncio.get_event_loop()
        anim   = asyncio.create_task(_anim_loop(status, "📷 Analysing your image..."))
        analysis = await loop.run_in_executor(
            _executor, call_vision_ai, b64, "image/jpeg", caption)
        anim.cancel()
        try: await anim
        except asyncio.CancelledError: pass

        if uid not in user_memory:
            user_memory[uid] = []
        user_memory[uid].append({"role": "user",      "content": f"[Image] {caption}"})
        user_memory[uid].append({"role": "assistant",  "content": analysis})

        await status.delete()
        await update.message.reply_text(f"🔍 *Image Analysis:*\n\n{analysis}", parse_mode="Markdown")

    except Exception as e:
        await status.delete()
        await update.message.reply_text(f"⚠️ Image analysis failed: {e}")


async def _handle_avatar(update, context, uid, caption):
    """Cinematic pipeline: photo → Vision describe → Pollinations 3D Pixar avatar."""
    status = await update.message.reply_text("🎬 Scanning your photo...\n⬜⬜⬜⬜⬜⬜⬜⬜")

    try:
        photo      = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        raw_bytes  = await photo_file.download_as_bytearray()
        b64        = base64.b64encode(bytes(raw_bytes)).decode("utf-8")

        loop = asyncio.get_event_loop()

        # Step 1 — Describe person with Vision AI
        anim = asyncio.create_task(_anim_loop(status, "🧑‍🚀 Scanning your face..."))
        desc = await loop.run_in_executor(
            _executor, call_vision_ai, b64, "image/jpeg",
            "Describe this person for a 3D avatar. List: gender, approximate age, hair color and style, "
            "skin tone. Under 15 words. Only descriptors, no sentences.")
        anim.cancel()
        try: await anim
        except asyncio.CancelledError: pass

        # Clean up description
        desc = desc.replace("\n", ", ").strip()[:120]

        await status.edit_text(f"🎨 Creating 3D avatar...\n⬜⬜⬜⬜⬜⬜⬜⬜")

        # Step 2 — Generate avatar image
        avatar_prompt = (
            f"3D Pixar-style cartoon avatar character, {desc}, "
            "professional studio lighting, white background, ultra detailed, "
            "3D render, cinema4d, octane, vibrant colors, high quality"
        )
        anim2 = asyncio.create_task(_anim_loop(status, "🎨 Creating 3D avatar..."))

        def _fetch_avatar():
            encoded = urllib.parse.quote(avatar_prompt)
            seed    = random.randint(1, 999_999)
            url     = _POLL_URL.format(prompt=encoded, seed=seed)
            resp    = requests.get(url, timeout=90)
            return resp.content if resp.status_code == 200 else None

        img_bytes = await loop.run_in_executor(_executor, _fetch_avatar)
        anim2.cancel()
        try: await anim2
        except asyncio.CancelledError: pass

        await status.delete()

        if img_bytes:
            await update.message.reply_photo(
                photo=img_bytes,
                caption=(
                    f"🎬 *Cinematic Avatar Created!*\n"
                    f"🎨 _{desc[:80]}_\n\n"
                    f"_Powered by CC PIC 2.5 Flash_"
                ),
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("⚠️ Avatar generation failed. Please try again.")

    except Exception as e:
        await status.delete()
        await update.message.reply_text(f"⚠️ Avatar creation failed: {e}")


async def _handle_t2i_photo(update, context, uid, caption):
    """
    Text → Image + photo upload:
    Uses caption if given, otherwise falls back to the last
    text prompt the user typed — so upload works seamlessly.
    """
    # Priority: caption → last user message in memory → ask
    prompt = caption.strip()
    if not prompt and uid in user_memory:
        for msg in reversed(user_memory[uid]):
            if msg["role"] == "user" and not msg["content"].startswith("[Image"):
                prompt = msg["content"].strip()
                break

    if not prompt:
        await update.message.reply_text(
            "🖼️ *Text → Image*\n\n"
            "Please type your prompt first, then upload the photo.\n\n"
            "Example: _a futuristic cyberpunk city at night_",
            parse_mode="Markdown",
        )
        return

    status = await update.message.reply_text("🖼️ Generating your image...\n⬜⬜⬜⬜⬜⬜⬜⬜")
    loop = asyncio.get_event_loop()

    def _fetch_t2i():
        url  = make_image(prompt, BTN_T2I)
        resp = requests.get(url, timeout=90)
        return resp.content if resp.status_code == 200 else None

    anim = asyncio.create_task(_anim_loop(status, "🖼️ Generating your image..."))
    img_bytes = await loop.run_in_executor(_executor, _fetch_t2i)
    anim.cancel()
    try: await anim
    except asyncio.CancelledError: pass

    await status.delete()

    if img_bytes:
        await update.message.reply_photo(
            photo=img_bytes,
            caption=(
                f"🖼️ *Image Generated!*\n"
                f"📝 _{prompt[:200]}_\n\n"
                f"_Powered by CC PIC 2.5 Flash_"
            ),
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("⚠️ Image generation failed. Please try again.")

# ════════════════════════════════════════════════
#  DOCUMENT HANDLER
# ════════════════════════════════════════════════

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.message.chat_id, update)
    doc = update.message.document
    await update.message.reply_text(
        f"📁 *File received:* `{doc.file_name}`\n\n"
        "Paste the text content here and use *Research → Article Summary* for analysis.",
        parse_mode="Markdown",
    )

# ════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════

keep_alive()

bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

bot_app.add_handler(CommandHandler("start",   cmd_start))
bot_app.add_handler(CommandHandler("reset",   cmd_reset))
bot_app.add_handler(CommandHandler("help",    cmd_help))
bot_app.add_handler(CommandHandler("message", cmd_broadcast))
bot_app.add_handler(CommandHandler("users",   cmd_users))
bot_app.add_handler(CommandHandler("status",  cmd_status))
bot_app.add_handler(CommandHandler("chart",   cmd_chart))
bot_app.add_handler(MessageHandler(filters.PHOTO,        handle_photo))
bot_app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

print("✅ CC AI Bot v3.2 Running...")
bot_app.run_polling()
