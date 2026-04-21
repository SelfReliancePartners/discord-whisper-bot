import os
import io
import discord
from faster_whisper import WhisperModel

# モデルを読み込む（起動時に1回だけ）
model = WhisperModel("tiny", device="cpu")

def transcribe_local(audio_path):
    segments, info = model.transcribe(audio_path, language="ja")
    text = "".join([seg.text for seg in segments])
    return text

from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(dotenv_path="./.env")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands synced: {len(synced)}")
    except Exception as e:
        print(e)


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
            text = transcribe_local("audio.wav")
            results.append(f"🎧 **{mid}**:\n{text}")
        except Exception as e:
            results.append(f"❌ **{mid}**: Whisperエラー → {e}")

    output = "\n\n".join(results)
    if len(output) > 1900:
        output = output[:1900] + "…（省略）"

    await interaction.followup.send(f"📝 **文字起こし結果（{len(ids)}件）**\n\n{output}")


bot.run(DISCORD_TOKEN)
