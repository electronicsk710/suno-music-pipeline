import os
import json
import glob
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import LabelEncoder

# ----------------------------------------------------------------------
# Dataset class with chroma features (12-bin pitch class profile)
# ----------------------------------------------------------------------
class HarmonyDataset(Dataset):
    def __init__(self, json_files):
        self.samples = []
        self.chord_encoder = LabelEncoder()
        all_chords = set()
        for jf in json_files:
            with open(jf) as f:
                data = json.load(f)
            for chord in data['chords']:
                all_chords.add(chord)
        self.chord_encoder.fit(list(all_chords))

        for jf in json_files:
            with open(jf) as f:
                data = json.load(f)
            # Import quantize_notes from app.py (or implement locally)
            from app import quantize_notes
            notes = quantize_notes(data['notes'], data['tempo'])
            bar_duration = 4 * 60.0 / data['tempo']
            num_bars = len(data['chords'])
            bars = [[] for _ in range(num_bars)]
            for n in notes:
                bar_idx = int(round(n['start'] / bar_duration))
                if 0 <= bar_idx < num_bars:
                    bars[bar_idx].append(n)

            for bar_idx, bar_notes in enumerate(bars):
                # Build chroma vector: sum of durations per pitch class
                chroma = [0.0] * 12
                for n in bar_notes:
                    pc = n['pitch'] % 12
                    duration = n['end'] - n['start']
                    chroma[pc] += duration
                total_dur = sum(chroma)
                if total_dur > 0:
                    chroma = [c / total_dur for c in chroma]
                features = chroma  # 12 features
                chord_label = self.chord_encoder.transform([data['chords'][bar_idx]])[0]
                self.samples.append((features, chord_label))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        features, label = self.samples[idx]
        return torch.tensor(features, dtype=torch.float32), torch.tensor(label, dtype=torch.long)

# ----------------------------------------------------------------------
# Model (12 inputs, hidden layer, output classes)
# ----------------------------------------------------------------------
class SimpleHarmonyModel(nn.Module):
    def __init__(self, input_size=12, hidden_size=64, num_classes=10):
        super().__init__()
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(hidden_size, num_classes)

    def forward(self, x):
        x = self.fc1(x)
        x = self.relu(x)
        x = self.fc2(x)
        return x

# ----------------------------------------------------------------------
# Training loop
# ----------------------------------------------------------------------
def train(json_folder, model_save_path, epochs=20, batch_size=32, lr=0.001):
    json_files = glob.glob(os.path.join(json_folder, "*.json"))
    if not json_files:
        raise RuntimeError(f"No JSON files found in {json_folder}")
    dataset = HarmonyDataset(json_files)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    num_classes = len(dataset.chord_encoder.classes_)
    model = SimpleHarmonyModel(num_classes=num_classes)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)

    for epoch in range(epochs):
        total_loss = 0
        for features, labels in dataloader:
            optimizer.zero_grad()
            outputs = model(features)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        print(f"Epoch {epoch+1}/{epochs}, loss: {total_loss/len(dataloader):.4f}")

    torch.save({
        'model_state': model.state_dict(),
        'chord_encoder': dataset.chord_encoder
    }, model_save_path)
    print(f"Model saved to {model_save_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", required=True)
    parser.add_argument("--save_path", default="harmony_model.pt")
    args = parser.parse_args()
    train(args.data_dir, args.save_path)
