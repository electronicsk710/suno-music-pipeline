import os
import shutil
import tempfile
import json
from typing import List, Optional

import numpy as np
import librosa
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH

from midiutil import MIDIFile
from midi2audio import FluidSynth
from pydub import AudioSegment

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
SOUNDFONT_PATH = os.environ.get("SOUNDFONT_PATH", "FluidR3_GM.sf2")
app = FastAPI()

# Serve static frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

# ----------------------------------------------------------------------
# Pydantic schemas
# ----------------------------------------------------------------------
class Note(BaseModel):
    start: float
    end: float
    pitch: int
    velocity: float

class GenerateRequest(BaseModel):
    notes: List[Note]
    tempo: float
    key: str

# ----------------------------------------------------------------------
# 1. Melody extraction (pre‑trained Basic Pitch)
# ----------------------------------------------------------------------
def extract_melody_from_audio(audio_path, onset_threshold=0.5, frame_threshold=0.3):
    audio, sr = librosa.load(audio_path, sr=22050, mono=True)
    _, _, note_events = predict(
        audio,
        model_or_model_path=ICASSP_2022_MODEL_PATH,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        minimum_note_length=0.05,
        minimum_frequency=80,
        maximum_frequency=1000,
    )
    notes = []
    for ev in note_events:
        notes.append({
            'start': float(ev['start_time']),
            'end': float(ev['end_time']),
            'pitch': int(ev['pitch']),
            'velocity': float(ev['amplitude'])
        })
    return notes

# ----------------------------------------------------------------------
# 2. Tempo detection (vocal‑onset based, robust for a cappella)
# ----------------------------------------------------------------------
def detect_vocal_tempo(audio_path, sr=22050):
    """
    Estimate tempo from vocal onsets (no percussion needed).
    Falls back to 120 BPM if confidence is low.
    """
    y, sr = librosa.load(audio_path, sr=sr, mono=True)

    # Compute onset strength focused on vocal frequencies (200-2000 Hz)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    mask = (freqs >= 200) & (freqs <= 2000)
    onset_env = librosa.onset.onset_strength(S=S[mask], sr=sr, hop_length=512)

    # Detect onsets
    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, hop_length=512)

    if len(onset_frames) < 4:
        return 120.0

    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=512)
    iois = np.diff(onset_times)
    if len(iois) == 0:
        return 120.0

    ioi_median = np.median(iois)
    if ioi_median <= 0:
        return 120.0

    tempo = 60.0 / ioi_median
    tempo = int(round(tempo))
    if tempo < 60:
        tempo *= 2
    if tempo > 180:
        tempo //= 2
    return float(tempo)

# ----------------------------------------------------------------------
# 3. Key detection (pitch class histogram)
# ----------------------------------------------------------------------
def detect_key_from_notes(notes):
    if not notes:
        return "C major"
    hist = [0] * 12
    for n in notes:
        hist[n['pitch'] % 12] += 1

    major_profile = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
    minor_profile = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

    best_key = "C major"
    best_corr = -1.0
    for tonic in range(12):
        corr_maj = np.corrcoef(hist, np.roll(major_profile, tonic))[0, 1]
        if corr_maj > best_corr:
            best_corr = corr_maj
            best_key = f"{librosa.midi_to_note(tonic + 60)[:-1]} major"

        corr_min = np.corrcoef(hist, np.roll(minor_profile, tonic))[0, 1]
        if corr_min > best_corr:
            best_corr = corr_min
            best_key = f"{librosa.midi_to_note(tonic + 60)[:-1]} minor"

    return best_key

# ----------------------------------------------------------------------
# 4. Quantization (snap to 16th‑note grid)
# ----------------------------------------------------------------------
def quantize_notes(notes, tempo):
    if not notes:
        return notes

    bar_duration = 4 * 60.0 / tempo
    sixteenth = bar_duration / 16.0

    quantized = []
    for n in notes:
        # Convert to dict if needed
        if isinstance(n, Note):
            start = n.start
            end = n.end
            pitch = n.pitch
            velocity = n.velocity
        else:
            start = n['start']
            end = n['end']
            pitch = n['pitch']
            velocity = n.get('velocity', 0.8)

        start_q = round(start / sixteenth) * sixteenth
        end_q = round(end / sixteenth) * sixteenth

        if end_q - start_q < sixteenth:
            end_q = start_q + sixteenth

        quantized.append({
            'start': start_q,
            'end': end_q,
            'pitch': pitch,
            'velocity': velocity
        })
    return quantized

# ----------------------------------------------------------------------
# 5. Harmonization (accepts dicts or Pydantic models)
# ----------------------------------------------------------------------
def get_diatonic_triads(key_name):
    tonic_str, mode = key_name.split()
    tonic_pc = librosa.note_to_midi(tonic_str + '4') % 12
    if mode == 'major':
        intervals, qualities = [0, 2, 4, 5, 7, 9, 11], ['', 'm', 'm', '', '', 'm', 'dim']
    else:
        intervals, qualities = [0, 2, 3, 5, 7, 8, 10], ['m', 'dim', '', 'm', 'm', '', '']

    triads = []
    for i, interval in enumerate(intervals):
        root = (tonic_pc + interval) % 12
        chord_name = librosa.midi_to_note(root + 60)[:-1] + qualities[i]
        third = (root + (3 if qualities[i] in ['m', 'dim'] else 4)) % 12
        fifth = (root + (6 if qualities[i] == 'dim' else 7)) % 12
        triads.append((chord_name, [root, third, fifth]))
    return triads

def harmonize_melody(notes, tempo, key_name, time_signature=(4, 4)):
    # Normalize to list of dicts
    if notes and hasattr(notes[0], 'start'):
        notes = [{'start': n.start, 'end': n.end, 'pitch': n.pitch, 'velocity': n.velocity} for n in notes]

    bar_duration = time_signature[0] * 60.0 / tempo
    total_duration = max((n['end'] for n in notes), default=4.0) + bar_duration
    num_bars = int(np.ceil(total_duration / bar_duration))

    bars = {}
    for n in notes:
        bar_idx = int(n['start'] // bar_duration)
        bars.setdefault(bar_idx, []).append(n)

    triads = get_diatonic_triads(key_name)
    chord_progression = []

    for bar in range(num_bars):
        if bar not in bars:
            chord = chord_progression[-1] if chord_progression else triads[0][0]
            chord_progression.append(chord)
            continue

        best_score, best_chord = -1.0, triads[0][0]
        for chord_name, pcs in triads:
            score = sum((n['end'] - n['start']) for n in bars[bar] if n['pitch'] % 12 in pcs)
            if score > best_score:
                best_score, best_chord = score, chord_name
        chord_progression.append(best_chord)

    return chord_progression, bar_duration

# ----------------------------------------------------------------------
# 6. MIDI creation (correct timing & channels)
# ----------------------------------------------------------------------
def create_midi(melody_notes, chord_progression, tempo, bar_duration):
    """
    melody_notes: list of dicts (quantized)
    chord_progression: list of chord name strings
    tempo: BPM
    bar_duration: seconds per bar (4/4)
    """
    midi = MIDIFile(4)  # 4 tracks
    midi.addTempo(0, 0, tempo)

    beat_factor = tempo / 60.0  # beats per second

    # Track 0: Melody (channel 0, piano)
    midi.addProgramChange(0, 0, 0, 0)
    for n in melody_notes:
        start_beat = n['start'] * beat_factor
        dur_beat = (n['end'] - n['start']) * beat_factor
        vel = int(np.clip(n['velocity'] * 127, 0, 127))
        midi.addNote(0, 0, n['pitch'], start_beat, dur_beat, vel)

    # Track 1: Chords (channel 1, electric piano)
    midi.addProgramChange(1, 1, 0, 1)
    for i, chord in enumerate(chord_progression):
        root = chord[:2] if len(chord) > 1 and chord[1] in ['#', 'b'] else chord[0]
        quality = chord[len(root):]
        root_pc = librosa.note_to_midi(root + '4') % 12
        if quality == '':
            pcs = [root_pc, (root_pc+4)%12, (root_pc+7)%12]
        elif quality == 'm':
            pcs = [root_pc, (root_pc+3)%12, (root_pc+7)%12]
        else:  # dim
            pcs = [root_pc, (root_pc+3)%12, (root_pc+6)%12]

        start_beat = i * bar_duration * beat_factor
        dur_beat = bar_duration * 0.8 * beat_factor
        for pc in pcs:
            midi.addNote(1, 1, pc + 60, start_beat, dur_beat, 80)

    # Track 2: Bass (channel 2, acoustic bass)
    midi.addProgramChange(2, 2, 0, 32)
    for i, chord in enumerate(chord_progression):
        root = chord[:2] if len(chord) > 1 and chord[1] in ['#', 'b'] else chord[0]
        root_pc = librosa.note_to_midi(root + '3')  # bass octave
        start_beat = i * bar_duration * beat_factor
        dur_beat = 0.5 * beat_factor
        midi.addNote(2, 2, root_pc, start_beat, dur_beat, 90)
        # Add a second bass note on beat 3
        midi.addNote(2, 2, root_pc, start_beat + 2.0, dur_beat, 90)

    # Track 3: Drums (channel 9)
    for i in range(len(chord_progression)):
        b_start = i * bar_duration * beat_factor
        beat_dur = 1.0  # in beats (quarter note)
        # Kick on beats 1 and 3
        midi.addNote(3, 9, 35, b_start, 0.5, 100)
        midi.addNote(3, 9, 35, b_start + 2.0, 0.5, 100)
        # Snare on beats 2 and 4
        midi.addNote(3, 9, 38, b_start + 1.0, 0.5, 80)
        midi.addNote(3, 9, 38, b_start + 3.0, 0.5, 80)

    return midi

# ----------------------------------------------------------------------
# 7. Audio rendering
# ----------------------------------------------------------------------
def render_midi_to_wav(midi_path, soundfont_path, output_path):
    if not os.path.exists(soundfont_path):
        raise FileNotFoundError(f"SoundFont not found at {soundfont_path}")
    fs = FluidSynth(soundfont_path)
    fs.midi_to_audio(midi_path, output_path)

# ----------------------------------------------------------------------
# FastAPI routes
# ----------------------------------------------------------------------
@app.post("/analyze")
async def analyze_vocal(file: UploadFile = File(...)):
    temp_dir = tempfile.mkdtemp()
    vocal_path = os.path.join(temp_dir, file.filename or "vocal.wav")
    with open(vocal_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        notes = extract_melody_from_audio(vocal_path)
        tempo = detect_vocal_tempo(vocal_path)
        key = detect_key_from_notes(notes)
        return {"notes": notes, "tempo": tempo, "key": key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

@app.post("/generate")
async def generate_instrumental(req: GenerateRequest, background_tasks: BackgroundTasks):
    # Quantize melody
    quantized = quantize_notes(req.notes, req.tempo)
    chords, bar_duration = harmonize_melody(quantized, req.tempo, req.key)
    midi = create_midi(quantized, chords, req.tempo, bar_duration)

    temp_dir = tempfile.mkdtemp()
    midi_path = os.path.join(temp_dir, "output.mid")
    master_wav = os.path.join(temp_dir, "master.wav")
    final_wav = os.path.join(temp_dir, "final.wav")

    try:
        with open(midi_path, "wb") as f:
            midi.writeFile(f)

        render_midi_to_wav(midi_path, SOUNDFONT_PATH, master_wav)
        sound = AudioSegment.from_wav(master_wav).normalize(headroom=0.1)
        sound.export(final_wav, format="wav")
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Audio rendering error: {str(e)}")

    # Cleanup after response is sent
    def cleanup():
        shutil.rmtree(temp_dir, ignore_errors=True)
    background_tasks.add_task(cleanup)

    return FileResponse(final_wav, media_type="audio/wav", filename="instrumental.wav")

# Serve index.html at root
@app.get("/")
async def root():
    return FileResponse("static/index.html")
