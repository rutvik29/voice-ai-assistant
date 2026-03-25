"""Voice AI WebSocket server."""
import asyncio, base64, json, os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import openai

app = FastAPI(title="Voice AI Assistant")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
CONVERSATIONS: dict = {}


async def transcribe_audio(audio_bytes: bytes) -> str:
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        tmp = f.name
    try:
        with open(tmp, "rb") as audio_file:
            result = await client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        return result.text
    finally:
        os.unlink(tmp)


async def get_llm_response(session_id: str, user_text: str) -> str:
    if session_id not in CONVERSATIONS:
        CONVERSATIONS[session_id] = [{"role": "system", "content": "You are a helpful voice assistant. Be concise and conversational."}]
    CONVERSATIONS[session_id].append({"role": "user", "content": user_text})
    response = await client.chat.completions.create(model="gpt-4o", messages=CONVERSATIONS[session_id])
    assistant_text = response.choices[0].message.content
    CONVERSATIONS[session_id].append({"role": "assistant", "content": assistant_text})
    return assistant_text


async def synthesize_speech(text: str) -> bytes:
    response = await client.audio.speech.create(model="tts-1", voice="nova", input=text, response_format="mp3")
    return response.content


@app.websocket("/ws/{session_id}")
async def voice_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_bytes()
            await websocket.send_json({"type": "transcribing"})
            transcript = await transcribe_audio(data)
            await websocket.send_json({"type": "transcript", "text": transcript})
            llm_text = await get_llm_response(session_id, transcript)
            await websocket.send_json({"type": "response", "text": llm_text})
            audio_bytes = await synthesize_speech(llm_text)
            await websocket.send_bytes(audio_bytes)
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        CONVERSATIONS.pop(session_id, None)

@app.get("/health")
def health(): return {"status": "ok"}
