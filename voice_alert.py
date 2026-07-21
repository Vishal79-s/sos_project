"""
voice_alert.py
---------------
Generates a real spoken "Emergency Alert" voice message using pyttsx3,
which wraps each OS's own built-in text-to-speech engine:
    - Windows -> SAPI5 (built into Windows, no extra download needed)
    - macOS   -> NSSpeechSynthesizer (built in)
    - Linux   -> espeak (install with: sudo apt install espeak)

The final .wav attached to each SOS email is:
    [ 2s siren tone ]  +  [ spoken "Emergency alert. <patient> ... " ]

If pyttsx3 or the OS speech engine isn't available for any reason, this
falls back to a siren-only .wav so email sending never breaks.
"""

import wave
import struct
import math
import os

SAMPLE_RATE = 44100


def _generate_siren_frames(duration=2.0, sample_rate=SAMPLE_RATE):
    """Raw PCM16 mono frames for a short rising/falling siren tone."""
    n_samples = int(duration * sample_rate)
    amplitude = 20000
    frames = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        cycle_pos = t % 1.0
        if cycle_pos < 0.5:
            freq = 600 + (cycle_pos / 0.5) * 600
        else:
            freq = 1200 - ((cycle_pos - 0.5) / 0.5) * 600
        sample = amplitude * math.sin(2 * math.pi * freq * t)
        frames += struct.pack("<h", int(sample))
    return bytes(frames)


def _pick_female_voice(engine):
    """Looks through the OS's installed TTS voices and selects a female one
    if available (e.g. 'Microsoft Zira' on Windows, 'Samantha' on macOS,
    'english+f3' on espeak/Linux). Falls back to the default voice if no
    female voice is found."""
    try:
        voices = engine.getProperty("voices")
        for v in voices:
            name = (getattr(v, "name", "") or "").lower()
            vid = (getattr(v, "id", "") or "").lower()
            gender = getattr(v, "gender", None)
            is_female = (
                (gender and str(gender).lower() == "female")
                or "female" in name or "female" in vid
                or "zira" in name or "zira" in vid
                or "samantha" in name or "samantha" in vid
                or "susan" in name or "susan" in vid
                or "+f" in vid  # espeak female variants, e.g. english+f3
            )
            if is_female:
                engine.setProperty("voice", v.id)
                return True
    except Exception as e:
        print(f"[VOICE] Could not select a female voice, using default: {e}")
    return False


def _speak_to_wav(text, tmp_path="_voice_tmp.wav"):
    """Uses pyttsx3 (OS-native TTS) to synthesize `text` to a wav file.
    Returns the path on success, or None if unavailable."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 165)
        _pick_female_voice(engine)
        engine.save_to_file(text, tmp_path)
        engine.runAndWait()
        engine.stop()
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            return tmp_path
        return None
    except Exception as e:
        print(f"[VOICE] pyttsx3 TTS unavailable, falling back to siren-only: {e}")
        return None


def generate_alert_audio(patient_name, hospital_name, path="emergency_alert.wav"):
    """Builds the final siren + spoken-alert .wav attached to SOS emails."""
    message = (
        f"Emergency alert. {patient_name} has met with an accident. "
        f"Nearest hospital is {hospital_name}. Please respond immediately."
    )

    tmp_speech_path = path + "._speech_tmp.wav"
    speech_path = _speak_to_wav(message, tmp_speech_path)

    if speech_path:
        # Read back the TTS wav to see what format the OS engine actually
        # produced, then generate the siren at that *same* rate/format so
        # the two segments concatenate cleanly into one valid wav file.
        with wave.open(speech_path, "rb") as sw:
            rate = sw.getframerate()
            width = sw.getsampwidth()
            channels = sw.getnchannels()
            speech_frames = sw.readframes(sw.getnframes())
        os.remove(speech_path)

        if width == 2 and channels == 1:
            siren_frames = _generate_siren_frames(duration=2.0, sample_rate=rate)
            with wave.open(path, "w") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(rate)
                out.writeframes(siren_frames)
                out.writeframes(speech_frames)
            return path
        else:
            # Unusual format from this engine (rare) — safest fallback is
            # to just keep the original TTS file as-is rather than risk a
            # corrupted concatenation.
            os.replace(speech_path if os.path.exists(speech_path) else tmp_speech_path, path) \
                if os.path.exists(tmp_speech_path) else None

    # No usable speech output — siren-only fallback
    siren_frames = _generate_siren_frames(duration=3.0, sample_rate=SAMPLE_RATE)
    with wave.open(path, "w") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(siren_frames)

    return path


if __name__ == "__main__":
    p = generate_alert_audio("Demo Driver", "Amudham Hospitals", "emergency_alert.wav")
    print(f"Generated {p}")
