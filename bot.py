import logging
import aiohttp
import asyncio

# --- ログ最適化 ---
logging.basicConfig(level=logging.INFO)
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.client").setLevel(logging.ERROR)
logging.getLogger("aiohttp").setLevel(logging.ERROR)
logging.getLogger("aiohttp.websocket").setLevel(logging.ERROR)

# --- print の代わり ---
DEBUG = False
def log(*args):
    if DEBUG:
        print(*args)

# --- 安全な送信関数 ---
async def safe_send(channel, content=None, file=None):
    try:
        if file:
            await channel.send(content, file=file)
        else:
            await channel.send(content)
    except Exception:
        pass  # Render Free の切断は無視

# =========================================================
# 🔥 ここにダミーHTTPサーバーを追加（Render Web Service 安定化）
# =========================================================
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer

def run_dummy_server():
    server = HTTPServer(("0.0.0.0", 10000), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()
# =========================================================

import os
import io
import discord
from faster_whisper import WhisperModel

# モデルを読み込む（起動時に1回だけ）
#　model = WhisperModel("tiny", device="cpu")
model = WhisperModel("distil-small.en", device="cpu", compute_type="int8")

def transcribe_local(audio_path):
    segments, info = model.transcribe(
        audio_path,
        language="ja",
        beam_size=5,
        vad_filter=True,
        temperature=0.0,
        best_of=3
    )
    text = "".join([seg.text for seg in segments])
    return text
# --- Whisper を非同期で動かすためのラッパ ---
import asyncio

# --- Render Web Service を落とさないための keep-alive タスク ---
async def keep_alive():
    import aiohttp
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                await session.get("http://localhost:10000")
        except:
            pass
        await asyncio.sleep(15)  # 15秒ごとに送る（負荷ほぼゼロ）
        
async def transcribe_async(path: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, transcribe_local, path)

from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv(dotenv_path="./.env")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    log(f"Logged in as {bot.user}")
    
    # 🔥 keep-alive をバックグラウンドで起動
    bot.loop.create_task(keep_alive())
    
    try:
        synced = await bot.tree.sync()
        log(f"Slash commands synced: {len(synced)}")
    except Exception as e:
        log(e)


@bot.tree.command(
    name="transcribe",
    description="複数のメッセージIDの音声をまとめて文字起こしします"
)
@app_commands.describe(
    message_ids="スペース区切りでメッセージIDを複数入力（例: 123 456 789）"
)
async def transcribe(interaction: discord.Interaction, message_ids: str):

    await interaction.response.defer(thinking=True)

    channel = interaction.channel

    ids = message_ids.split()
    results = []

    for mid in ids:
        try:
            msg = await channel.fetch_message(int(mid))
        except:
            results.append(f"❌ **{mid}**: メッセージが見つかりません")
            continue

        if not msg.attachments:
            results.append(f"❌ **{mid}**: 添付ファイルなし")
            continue

        attachment = msg.attachments[0]

        if not attachment.filename.lower().endswith((".ogg", ".mp3", ".wav", ".m4a", ".webm")):
            results.append(f"❌ **{mid}**: 音声ファイルではありません")
            continue

        audio_bytes = await attachment.read()
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = attachment.filename

        try:
# 一時ファイルとして保存
            with open("audio.wav", "wb") as f:
                f.write(audio_bytes)
               
# ローカル Whisper で文字起こし
            text = await transcribe_async("audio.wav")
            results.append(f"🎧 **{mid}**:\n{text}")
        except Exception as e:
            results.append(f"❌ **{mid}**: Whisperエラー → {e}")

    output = "\n\n".join(results)
    if len(output) > 1900:
        output = output[:1900] + "…（省略）"

    await interaction.followup.send(f"📝 **文字起こし結果（{len(ids)}件）**\n\n{output}")

@bot.event
async def on_message(message):
    # Bot自身のメッセージは無視
    if message.author.bot:
        return

    # 添付ファイルがない場合は無視
    if not message.attachments:
        return

    attachment = message.attachments[0]

    # 音声ファイルかどうか判定
    if not attachment.filename.lower().endswith((".ogg", ".mp3", ".wav", ".m4a", ".webm")):
        return

    try:
        audio_bytes = await attachment.read()
        with open("auto_audio.wav", "wb") as f:
            f.write(audio_bytes)

        text = await transcribe_async("auto_audio.wav")

        await safe_send(
            message.channel,
            f"📝 **自動文字起こし（{attachment.filename}）**\n{text}"
        )

    except Exception as e:
        await safe_send(
            message.channel,
            f"❌ 自動文字起こしエラー: {e}")

    # 重要：on_message を使うときは commands の処理も通す
    await bot.process_commands(message)



bot.run(DISCORD_TOKEN)
