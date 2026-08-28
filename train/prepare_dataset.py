import os
import sys
import json

# Add project root to path so we can import from app.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import extract_melody_from_audio, detect_vocal_tempo, detect_key_from_notes, harmonize_melody

def process_audio_folder(input_dir, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    for fname in os.listdir(input_dir):
        if not fname.lower().endswith(('.wav', '.mp3', '.flac', '.m4a')):
            continue
        path = os.path.join(input_dir, fname)
        try:
            notes = extract_melody_from_audio(path)
            tempo = detect_vocal_tempo(path)
            key = detect_key_from_notes(notes)
            chords, _ = harmonize_melody(notes, tempo, key)
        except Exception as e:
            print(f"Skipping {fname}: {e}")
            continue

        data = {
            "audio": fname,
            "tempo": tempo,
            "key": key,
            "notes": notes,
            "chords": chords
        }
        out_path = os.path.join(output_dir, fname + ".json")
        with open(out_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Processed {fname} -> {out_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python prepare_dataset.py <input_dir> <output_dir>")
        sys.exit(1)
    process_audio_folder(sys.argv[1], sys.argv[2])
