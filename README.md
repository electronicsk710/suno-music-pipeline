# Suno-style Music Generation Pipeline

A complete Suno-style music generation pipeline featuring vocal analysis, automatic harmonization, and MIDI rendering with realistic instruments.

## Features

✨ **Vocal Melody Extraction** - Detects pitch and timing from recorded or uploaded vocal
📊 **Robust Tempo Detection** - Analyzes vocal onsets to estimate tempo (no percussion needed)
🎵 **Automatic Key Detection** - Identifies the key using pitch class histogram correlation
🎼 **Intelligent Harmonization** - Generates diatonic chord progressions based on the melody
🎹 **MIDI Generation** - Creates multi-track MIDI with melody, chords, bass, and drums
🎧 **Audio Rendering** - Converts MIDI to WAV using realistic instrument sounds

## Project Structure

```
music_pipeline/
├── app.py                  # FastAPI backend
├── static/
│   └── index.html          # Frontend UI
├── train/
│   ├── prepare_dataset.py  # Convert audio to dataset
│   └── train_harmony.py    # Train chord prediction model
├── requirements.txt
└── FluidR3_GM.sf2          # SoundFont (download separately)
```

## System Dependencies

### Ubuntu/Debian
```bash
sudo apt install ffmpeg fluidsynth
```

### macOS
```bash
brew install ffmpeg fluid-synth
```

### SoundFont
Download a GM SoundFont like `FluidR3_GM.sf2` from [here](https://member.keymusician.com/Member/FluidR3_GM/index.html) and place it in the project root.

Alternatively, set the environment variable:
```bash
export SOUNDFONT_PATH=/path/to/your/soundfont.sf2
```

## Installation

```bash
pip install -r requirements.txt
```

## Running the Server

```bash
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000` in your browser.

### Usage

1. **Record or Upload** - Record a vocal melody with your mic or upload an audio file
2. **Analyze** - Click "Analyze Track" to extract notes, tempo, and key
3. **Customize** - Optionally override the detected tempo
4. **Generate** - Click "Generate Instrumental" to produce a WAV with full arrangement

## Training Your Own Harmonizer

1. Prepare a dataset of audio files:
```bash
python train/prepare_dataset.py <input_dir> <output_dir>
```

2. (Optional) Manually correct chord labels in the generated JSON files

3. Train the model:
```bash
cd train
python train_harmony.py --data_dir ../data/ --save_path harmony_model.pt
```

## Technical Architecture

### Backend (FastAPI)
- **Melody Extraction**: Uses pre-trained Basic Pitch model
- **Tempo Detection**: Onset-strength analysis on vocal frequency range (200-2000 Hz)
- **Key Detection**: Pitch class histogram correlation with major/minor profiles
- **Quantization**: Snaps notes to 16th-note grid for MIDI timing precision
- **Harmonization**: Rule-based diatonic chord selection (or trained model)
- **MIDI Generation**: Multi-track MIDI with melody, chords, bass, and drums
- **Audio Rendering**: FluidSynth + SoundFont for realistic instrument sounds

### Frontend (HTML/JS)
- Microphone recording with WebRTC
- File upload support
- Real-time audio preview
- Tempo override controls
- Interactive music player

## Bug Fixes & Improvements

✅ **MIDI Timing** - Correct beat factor calculation and note duration handling
✅ **Channel Management** - Proper MIDI channel assignment (0-2 for synth, 9 for drums)
✅ **Type Safety** - Consistent dict/Pydantic model handling throughout
✅ **Import Fixes** - All required dependencies properly imported and configured
✅ **Temporal Quantization** - Robust 16th-note grid snapping
✅ **Vocal Tempo Detection** - Reliable tempo estimation from onsets alone
✅ **Chroma Features** - 12-bin pitch class profile for accurate harmonization

## API Endpoints

### POST `/analyze`
Analyze an audio file for melody, tempo, and key.

**Request**: Multipart form with audio file

**Response**:
```json
{
  "notes": [
    {"start": 0.0, "end": 0.5, "pitch": 60, "velocity": 0.8},
    ...
  ],
  "tempo": 120.0,
  "key": "C major"
}
```

### POST `/generate`
Generate an instrumental WAV file with harmonization.

**Request**:
```json
{
  "notes": [...],
  "tempo": 120.0,
  "key": "C major"
}
```

**Response**: WAV audio file

## License

MIT

## Contributing

Contributions welcome! Please open issues or submit pull requests.
