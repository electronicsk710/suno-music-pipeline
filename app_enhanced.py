import os
import shutil
import tempfile
import json
from typing import List, Optional
from datetime import datetime

import numpy as np
import librosa
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH

from midiutil import MIDIFile
from midi2audio import FluidSynth
from pydub import AudioSegment

from logger_config import logger

# Load configuration
with open('config.json', 'r') as f:
    CONFIG = json.load(f)

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
SOUNDFONT_PATH = os.environ.get("SOUNDFONT_PATH", "FluidR3_GM.sf2")
app = FastAPI(title="Suno Music Pipeline", version="1.0.0")

# Serve static frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

# Track request metrics
request_stats = {
    "analyze_count": 0,
    "generate_count": 0,
    "errors": 0,
    "start_time": datetime.now()
}

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

class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    requests_processed: int
    errors: int
    soundfont_available: bool

# ----------------------------------------------------------------------
# Health Check Endpoint
# ----------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint for deployment monitoring.
    """
    try:
        uptime = (datetime.now() - request_stats["start_time"]).total_seconds()
        soundfont_exists = os.path.exists(SOUNDFONT_PATH)
        
        logger.info(f"Health check - Status: healthy, SoundFont: {soundfont_exists}")
        
        return HealthResponse(
            status="healthy",
            uptime_seconds=uptime,
            requests_processed=request_stats["analyze_count"] + request_stats["generate_count"],
            errors=request_stats["errors"],
            soundfont_available=soundfont_exists
        )
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")

# ----------------------------------------------------------------------
# Metrics Endpoint
# ----------------------------------------------------------------------
@app.get("/stats")
async def get_stats():
    """
    Get application statistics.
    """
    uptime = (datetime.now() - request_stats["start_time"]).total_seconds()
    total_requests = request_stats["analyze_count"] + request_stats["generate_count"]
    error_rate = (request_stats["errors"] / total_requests * 100) if total_requests > 0 else 0
    
    return {
        "uptime_seconds": uptime,
        "analyze_requests": request_stats["analyze_count"],
        "generate_requests": request_stats["generate_count"],
        "total_requests": total_requests,
        "errors": request_stats["errors"],
        "error_rate_percent": round(error_rate, 2),
        "soundfont_path": SOUNDFONT_PATH,
        "soundfont_available": os.path.exists(SOUNDFONT_PATH)
    }

# ----------------------------------------------------------------------
# 1. Melody extraction (pre‑trained Basic Pitch)
# ----------------------------------------------------------------------
def extract_melody_from_audio(audio_path, onset_threshold=None, frame_threshold=None):
    """Extract melody from audio using Basic Pitch model."""
    try:
        if onset_threshold is None:
            onset_threshold = CONFIG["pitch_detection"]["onset_threshold"]
        if frame_threshold is None:
            frame_threshold = CONFIG["pitch_detection"]["frame_threshold"]
        
        logger.info(f"Extracting melody from {audio_path}")
        
        audio, sr = librosa.load(audio_path, sr=CONFIG["audio"]["sample_rate"], mono=CONFIG["audio"]["mono"])
        _, _, note_events = predict(
            audio,
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            onset_threshold=onset_threshold,
            frame_threshold=frame_threshold,
            minimum_note_length=CONFIG["audio"]["minimum_note_length"],
            minimum_frequency=CONFIG["audio"]["min_frequency"],
            maximum_frequency=CONFIG["audio"]["max_frequency"],
        )
        notes = []
        for ev in note_events:
            notes.append({
                'start': float(ev['start_time']),
                'end': float(ev['end_time']),
                'pitch': int(ev['pitch']),
                'velocity': float(ev['amplitude'])
            })
        
        logger.info(f"Extracted {len(notes)} notes")
        return notes
    except Exception as e:
        logger.error(f"Melody extraction failed: {str(e)}")
        raise

# ----------------------------------------------------------------------
# 2. Tempo detection (vocal‑onset based, robust for a cappella)
# ----------------------------------------------------------------------
def detect_vocal_tempo(audio_path, sr=None):
    """
    Estimate tempo from vocal onsets (no percussion needed).
    Falls back to 120 BPM if confidence is low.
    """
    try:
        if sr is None:
            sr = CONFIG["audio"]["sample_rate"]
        
        logger.info(f"Detecting tempo from {audio_path}")
        
        y, sr = librosa.load(audio_path, sr=sr, mono=CONFIG["audio"]["mono"])

        # Compute onset strength focused on vocal frequencies
        S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
        mask = (freqs >= CONFIG["tempo"]["vocal_freq_min"]) & (freqs <= CONFIG["tempo"]["vocal_freq_max"])
        onset_env = librosa.onset.onset_strength(S=S[mask], sr=sr, hop_length=512)

        # Detect onsets
        onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, hop_length=512)

        if len(onset_frames) < CONFIG["tempo"]["min_onsets"]:
            logger.warning(f"Low onset confidence, using default {CONFIG['tempo']['default_bpm']} BPM")
            return float(CONFIG["tempo"]["default_bpm"])

        onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=512)
        iois = np.diff(onset_times)
        if len(iois) == 0:
            return float(CONFIG["tempo"]["default_bpm"])

        ioi_median = np.median(iois)
        if ioi_median <= 0:
            return float(CONFIG["tempo"]["default_bpm"])

        tempo = 60.0 / ioi_median
        tempo = int(round(tempo))
        
        # Constrain tempo to reasonable range
        if tempo < CONFIG["tempo"]["min_bpm"]:
            tempo *= 2
        if tempo > CONFIG["tempo"]["max_bpm"]:
            tempo //= 2
        
        logger.info(f"Detected tempo: {tempo} BPM")
        return float(tempo)
    except Exception as e:
        logger.error(f"Tempo detection failed: {str(e)}")
        return float(CONFIG["tempo"]["default_bpm"])

# ----------------------------------------------------------------------
# 3. Key detection (pitch class histogram)
# ----------------------------------------------------------------------
def detect_key_from_notes(notes):
    """Detect key using pitch class histogram correlation."""
    try:
        if not notes:
            logger.warning("No notes provided, using default C major")
            return "C major"
        
        logger.info("Detecting key from notes")
        
        hist = [0] * 12
        for n in notes:
            hist[n['pitch'] % 12] += 1

        major_profile = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
        minor_profile = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

        best_key = "C major"
        best_corr = -1.0
        for tonic in range(12):
            corr_maj = np.corrcoef(hist, np.roll(major_profile, tonic))[0, 1]
            if not np.isnan(corr_maj) and corr_maj > best_corr:
                best_corr = corr_maj
                best_key = f"{librosa.midi_to_note(tonic + 60)[:-1]} major"

            corr_min = np.corrcoef(hist, np.roll(minor_profile, tonic))[0, 1]
            if not np.isnan(corr_min) and corr_min > best_corr:
                best_corr = corr_min
                best_key = f"{librosa.midi_to_note(tonic + 60)[:-1]} minor"

        logger.info(f"Detected key: {best_key}")
        return best_key
    except Exception as e:
        logger.error(f"Key detection failed: {str(e)}")
        return "C major"

# ----------------------------------------------------------------------
# 4. Quantization (snap to 16th‑note grid)
# ----------------------------------------------------------------------
def quantize_notes(notes, tempo):
    """Quantize notes to 16th-note grid."""
    try:
        if not notes:
            return notes

        grid_size = CONFIG["midi"]["quantization_grid"]
        bar_duration = CONFIG["harmonization"]["bar_duration_factor"] * 60.0 / tempo
        sixteenth = bar_duration / grid_size

        logger.info(f"Quantizing {len(notes)} notes to {grid_size}th-note grid")
        
        quantized = []
        for n in notes:
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
        
        logger.info(f"Quantized {len(quantized)} notes")
        return quantized
    except Exception as e:
        logger.error(f"Quantization failed: {str(e)}")
        return notes

# ----------------------------------------------------------------------
# 5. Harmonization
# ----------------------------------------------------------------------
def get_diatonic_triads(key_name):
    """Get diatonic triads for a given key."""
    try:
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
    except Exception as e:
        logger.error(f"Failed to get diatonic triads: {str(e)}")
        return [("C", [0, 4, 7])]

def harmonize_melody(notes, tempo, key_name, time_signature=(4, 4)):
    """Generate chord progression for melody."""
    try:
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

        logger.info(f"Generated {len(chord_progression)} chords")
        return chord_progression, bar_duration
    except Exception as e:
        logger.error(f"Harmonization failed: {str(e)}")
        return [], 4.0

# ... [Continue with remaining functions from original app.py]
# (create_midi, render_midi_to_wav, etc.)
