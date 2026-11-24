"""Voice for Quantora team messages (24 Nov 2026, owner approved "MP3 voice + alert").

Takes the team messages waiting for a voice from voice-worker, reads each one aloud with the free Piper voice
engine (en_US lessac, medium), encodes it as MP3 and uploads it to the one-time link voice-worker gives.
Zero cost: runs in this public repo's GitHub Actions. No key: the workflow proves itself with GitHub's OIDC token.
The public log shows message ids only, never the text.
"""
import json, os, subprocess, sys, tempfile, urllib.request, wave

URL = os.environ["VOICE_WORKER_URL"]
MODEL = os.environ.get("VOICE_MODEL", "en-us-lessac-medium.onnx")


def oidc():
    req = urllib.request.Request(os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=quantora-voice",
                                 headers={"Authorization": "bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})
    return json.load(urllib.request.urlopen(req, timeout=30))["value"]


def call(token, body):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", "x-github-oidc": token})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def to_mp3(wav_path):
    import lameenc
    with wave.open(wav_path, "rb") as w:
        enc = lameenc.Encoder()
        enc.set_bit_rate(64); enc.set_in_sample_rate(w.getframerate()); enc.set_channels(w.getnchannels()); enc.set_quality(2)
        data = enc.encode(w.readframes(w.getnframes()))
    return bytes(data + enc.flush())


def speak(text, tmp):
    wav = os.path.join(tmp, "m.wav")
    subprocess.run([sys.executable, "-m", "piper", "-m", MODEL, "-f", wav], input=text.encode(), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    return to_mp3(wav)


def main():
    token = oidc()
    done = failed = 0
    for _ in range(10):                                   # at most 100 messages in one run
        batch = call(token, {"action": "claim", "limit": 10}).get("messages", [])
        if not batch:
            break
        for m in batch:
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    mp3 = speak(m["text"], tmp)
                put = urllib.request.Request(m["upload_url"], data=mp3, method="PUT", headers={"content-type": "audio/mpeg", "x-upsert": "true"})
                urllib.request.urlopen(put, timeout=60).read()
                call(token, {"action": "done", "id": m["id"], "path": m["path"]})
                done += 1
                print(f"voice ready: {m['id']} ({len(mp3) // 1024} KB)")
            except Exception as e:                        # the text is always shown; the voice is a bonus
                failed += 1
                print(f"voice failed: {m['id']}: {type(e).__name__}")
                try:
                    call(token, {"action": "fail", "id": m["id"], "error": type(e).__name__})
                except Exception:
                    pass
    print(f"done: {done}, failed: {failed}")


if __name__ == "__main__":
    main()
