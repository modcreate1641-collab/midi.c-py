# 🎹 MIDI Master Synchronizer + BlackMIDI Merger

**Android-first MIDI processing for Termux. Built for tempo normalization, piano conversion, and sequential Black MIDI part merging.**

This repository documents two separate tools:

- **`MIDI_Master_Synchronizer_Combined.py`** — batch-processes MIDI files in three predefined folders, maps their event timing to a target BPM, normalizes notes to a fixed velocity, optionally forces a piano program and output channel, and generates JSON reports.
- **`BlackMIDI Merger (cpp).cpp`** — a C++17 command-line utility that discovers `PT<number>` MIDI parts, scans their note-event ranges, and concatenates usable parts sequentially into one Type 1 MIDI file.

> **Important:** These programs do different jobs. The Python script does not automatically invoke the C++ merger, and the C++ merger does not automatically run the Python synchronizer.

## Contents

- [Features](#features)
- [Tool 1 — MIDI Master Synchronizer](#tool-1--midi-master-synchronizer)
- [Tool 2 — BlackMIDI Merger](#tool-2--blackmidi-merger)
- [Android and Termux installation](#android-and-termux-installation)
- [Running the Python synchronizer](#running-the-python-synchronizer)
- [Building and running the C++ merger](#building-and-running-the-c-merger)
- [Recommended workflow](#recommended-workflow)
- [Usage rules and redistribution](#usage-rules-and-redistribution)
- [Limitations and troubleshooting](#limitations-and-troubleshooting)
- [Raspberry Pi OS (optional)](#raspberry-pi-os-optional)
- [Official references](#official-references)

## Features

### Python synchronizer

The supplied source currently defines these defaults:

| Setting | Default | Effect |
|---|---:|---|
| `TARGET_BPM` | `120.0` | Target tempo used by BPM-lock conversion |
| `FIXED_VELOCITY` | `90` | Velocity assigned to note-on events when normalization is enabled |
| `PIANO_PROGRAM` | `0` | General MIDI program number used for the output program change |
| `OUTPUT_CHANNEL` | `0` | Output MIDI channel when channel mapping is enabled |
| `ENABLE_BPM_LOCK` | `True` | Converts event ticks using the source tempo map and target tempo |
| `ENABLE_PIANO_MODE` | `True` | Adds a piano program change on the output channel |
| `ENABLE_FIXED_VELOCITY` | `True` | Normalizes note-on velocity |
| `ENABLE_CHANNEL_MAPPING` | `True` | Maps note events to the configured output channel |
| `ENABLE_REMOVE_NON_NOTE_EVENTS` | `True` | Removes non-note events, including meta events during collection |
| `ENABLE_TEMPO_CLEANING` | `True` | Removes source tempo events when BPM lock is enabled |
| `ENABLE_REPORT` | `True` | Writes per-folder and global JSON reports |

The script processes these folders:

```text
/sdcard/Download/
├── midi_input/
│   ├── folder_1/
│   ├── folder_2/
│   └── folder_3/
├── midi_fixed/
│   ├── folder_1/
│   ├── folder_2/
│   └── folder_3/
└── midi_reports/
    ├── folder_1/
    ├── folder_2/
    ├── folder_3/
    └── global_report.json
```

Input file extensions supported by the Python source: `.mid`, `.midi`, `.MID`, and `.MIDI`.

**Note duration is not capped or deliberately shortened by this script.** It maps note-event times according to its tempo conversion. Its default cleanup removes other event types, so it is not intended to preserve every original MIDI controller, instrument, lyric, marker, or other metadata event.

### C++ BlackMIDI merger

The supplied C++ source currently:

- Uses C++17 features, including `std::filesystem`.
- Creates its input, output, and temporary directories automatically.
- Looks for `.mid` and `.midi` files directly inside the input directory.
- Selects filenames containing `PT` followed by a part number; matching is case-insensitive and spaces, underscores, or hyphens before the number are accepted.
- Sorts matching files by part number, then by filename.
- Scans MIDI format 0 or 1 files and requires a compatible, positive ticks-per-beat division.
- Skips files that contain no detected note events.
- Merges the tracks within each source part by event time, then writes one output track for each usable part.
- Places the parts sequentially, rather than aligning every part to the same starting time.
- Writes to a temporary file, checks the output header, then renames it to the final destination.

Default paths in the supplied source:

```text
/sdcard/Download/BlackMIDI_Merger/
├── input/
├── output/
│   └── BlackMIDI_Merged.mid
└── temp/
    └── merged.tmp
```

The merger does **not** perform the same BPM-lock, fixed-velocity, or piano conversion as the Python script. It preserves many event bytes from the source tracks, but it trims each part to the detected note-event range and replaces the end-of-track event. See [Limitations](#limitations-and-troubleshooting).

## Android and Termux installation

This project is designed for local command-line use on Android through [Termux](https://github.com/termux/termux-app). A rooted phone is not inherently required.

### 1. Install Termux from an official source

Choose one source:

- **Termux on F-Droid:** https://f-droid.org/en/packages/com.termux/
- **Official Termux GitHub repository and releases:** https://github.com/termux/termux-app

Install Termux and its optional plugins from the same distribution source. APKs from different sources may use different signing keys and may not install over one another. Read the [official Termux installation instructions](https://github.com/termux/termux-app#installation).

### 2. Update packages

Open Termux and run:

```bash
pkg update
pkg upgrade
```

### 3. Install the required tools

```bash
pkg install python git clang
```

The Python script requires the `mido` package. Install it with:

```bash
python -m pip install mido
```

Mido's official source and installation guidance: https://github.com/mido/mido

### 4. Grant access to shared storage

```bash
termux-setup-storage
```

Accept Android's permission prompt. The source code uses `/sdcard/Download/...` paths; these are shared-storage paths, not paths inside the Termux home directory.

Verify access:

```bash
ls /sdcard/Download
```

If your device or Android configuration uses a different accessible path, update the `INPUT_ROOT`, `OUTPUT_ROOT`, and `REPORT_ROOT` constants in the Python script and the `BASE` constant in the C++ source. The directory paths are hard-coded in the supplied versions.

## Running the Python synchronizer

### 1. Prepare the folder structure

Run:

```bash
mkdir -p /sdcard/Download/midi_input/folder_1
mkdir -p /sdcard/Download/midi_input/folder_2
mkdir -p /sdcard/Download/midi_input/folder_3
```

Place the MIDI files to process inside the appropriate `folder_1`, `folder_2`, or `folder_3` directory. The script creates output and report directories automatically.

### 2. Put the script in an accessible location

For example, if the script is in Downloads:

```bash
cd /sdcard/Download
```

Confirm the file exists:

```bash
ls -l MIDI_Master_Synchronizer_Combined.py
```

### 3. Run it

```bash
python MIDI_Master_Synchronizer_Combined.py
```

Review the console output. Generated MIDI files are written to:

```text
/sdcard/Download/midi_fixed/folder_1/
/sdcard/Download/midi_fixed/folder_2/
/sdcard/Download/midi_fixed/folder_3/
```

Reports are written to:

```text
/sdcard/Download/midi_reports/
```

The global report is `global_report.json`.

### Configuration

Edit the constants near the beginning of `MIDI_Master_Synchronizer_Combined.py` before running it. For example, changing `TARGET_BPM` changes the target tempo. Make a backup before editing the script.

The script's `FOLDER_NAMES` list is currently fixed to `folder_1`, `folder_2`, and `folder_3`; it does not recursively scan an arbitrary directory tree.

## Building and running the C++ merger

### 1. Prepare the input directory

```bash
mkdir -p /sdcard/Download/BlackMIDI_Merger/input
mkdir -p /sdcard/Download/BlackMIDI_Merger/output
mkdir -p /sdcard/Download/BlackMIDI_Merger/temp
```

Place the source parts directly inside `input/`. Example names:

```text
PT 1.mid
PT 2.mid
PT_3.mid
PT-4.midi
```

The part number is used for sorting. Files without a `PT<number>` pattern are ignored. Files inside nested subdirectories are not searched.

### 2. Compile

Save the source as `BlackMIDI Merger (cpp).cpp` or use the filename present in your checkout. From the directory containing the source, run:

```bash
clang++ -O2 -std=c++17 \
  -include cstring -include cerrno \
  "BlackMIDI Merger (cpp).cpp" \
  -o blackmidi_merger
```

The explicit header flags accommodate the supplied source's use of `std::strerror` and `errno` without directly including `<cstring>` and `<cerrno>`. A cleaner source-level fix is to add those two includes and then remove the `-include` flags.

If compilation fails, read the actual compiler diagnostic; do not assume the executable was created.

### 3. Run

```bash
./blackmidi_merger
```

The program reports scan and merge progress. On success, the destination is:

```text
/sdcard/Download/BlackMIDI_Merger/output/BlackMIDI_Merged.mid
```

It also prints output size and elapsed time. These values depend on the input files and device; no universal speed or maximum note count is guaranteed.

## Recommended workflow

1. **Back up originals.**
2. Test the Python synchronizer on a small MIDI file and verify its output in a MIDI player or DAW.
3. If merging split parts, put the correctly named `PT<number>` files in the C++ merger's input directory.
4. Run the merger separately.
5. Validate the merged file's track count, tempo behavior, note timing, and playback.
6. Keep the JSON reports and console output when investigating problems.

Do not assume the two tools are an automatic pipeline. If you want synchronized/piano-normalized parts merged afterward, run the desired stages manually and verify the intermediate files.

## Usage rules and redistribution

By using or sharing this software, you agree to follow these project-use rules:

1. **Use MIDI files lawfully.** Only process, publish, or redistribute files you created, have permission to use, or are otherwise legally entitled to use.
2. **Respect licenses and attribution.** When sharing a MIDI file or a derivative, follow the original creator's license and attribution requirements. Processing a file does not remove its copyright or license restrictions.
3. **Credit upstream work.** If you redistribute this project, modified versions, or included third-party code, retain required copyright notices, licenses, and attribution. Include the original project URL and the exact revision where practical.
4. **Do not misrepresent authorship.** Clearly identify your modifications and do not claim that third-party MIDI files or code were created by you.
5. **Review before execution.** Do not run source code from an untrusted repository without inspecting it.
6. **Protect original data.** Keep backups and verify output paths before batch processing.
7. **Report bugs responsibly.** Include the device/OS version, command, relevant error message, and a minimal reproducible example. Do not upload copyrighted MIDI files or private data unless you have permission.
8. **No blanket redistribution permission is implied.** A repository without a clearly published license does not automatically grant permission to copy, modify, or redistribute its code. The repository owner should add a `LICENSE` file before describing the project as open source.

These rules are project guidance, not legal advice. Third-party MIDI files and dependencies may have separate terms.

## Limitations and troubleshooting

### Python synchronizer: event cleanup

With the default settings, non-note events are removed during collection. This can remove controller events (such as sustain pedal), instrument changes, lyrics, markers, and other metadata. The script then writes a single-track Type 0 MIDI file and inserts a target tempo event and, when enabled, a piano program change.

The code does not implement a note-duration cap. Its report configuration explicitly records `duration_cap: false`.

### Python synchronizer: unmatched notes

The script reports unmatched note events. MIDI files with missing note-off events, unusual overlapping repetitions of the same pitch/channel, or malformed event pairs may need manual inspection. Do not treat report counts alone as proof that a file is musically identical to the original.

### C++ merger: sequential concatenation, not parallel alignment

The merger calculates each part's first and last detected note-event ticks and appends the part after the preceding part's note duration. It is therefore a **sequential concatenator**, not a tool for stacking all parts at the same start time.

Events before a part's first detected note are shifted to that part's start; events after its last detected note are not written. The final end-of-track event is generated by the program. Source tempo events and other retained meta events may coexist across output tracks; inspect tempo behavior in your target DAW/player.

### C++ merger: input compatibility

The source accepts MIDI format 0 or 1, but rejects unsupported formats, SMPTE-style time division, and input parts with differing ticks-per-beat divisions. Files with no detected note events are skipped. The source also limits the number of output tracks to 65,535 and rejects a track payload exceeding the MIDI 32-bit track-length field.

### Common issues

| Symptom | Checks |
|---|---|
| `ModuleNotFoundError: No module named 'mido'` | Run `python -m pip install mido` |
| Input folder appears empty | Check the exact hard-coded path, folder names, file extensions, and Android storage permission |
| C++ merger finds no parts | Ensure files are directly in `input/` and filenames contain `PT` followed by a number |
| `Different MIDI time divisions` | Re-export source parts with matching ticks-per-beat settings |
| Compilation fails around `strerror` or `errno` | Use the compile command above or add `<cstring>` and `<cerrno>` to the source |
| Process is killed or the phone becomes unresponsive | Reduce the test workload, close other intensive apps, keep Termux in the foreground, and allow adequate free storage |
| Output plays differently | Check retained tempo events, event trimming, source timing, and the target player's MIDI interpretation |

Android may terminate resource-intensive or background processes. Keeping Termux in the foreground and avoiding simultaneous heavy workloads may help, but does not guarantee that a long job will complete.

## Raspberry Pi OS (optional)

Raspberry Pi is an optional Linux environment for testing these tools; it is not required for the Android workflow. Compatibility and performance must be verified on the exact board and OS image.

Official links:

- **Raspberry Pi OS documentation:** https://www.raspberrypi.com/documentation/computers/os.html
- **Raspberry Pi Imager downloads:** https://www.raspberrypi.com/software/
- **Getting started / OS installation:** https://www.raspberrypi.com/documentation/computers/getting-started.html

Install Raspberry Pi OS using Raspberry Pi Imager on a compatible computer and write it to the intended boot storage. **Writing an OS image erases the selected storage device. Back up files and verify the target device before writing.**

On Raspberry Pi OS, install common build tools:

```bash
sudo apt update
sudo apt full-upgrade
sudo apt install python3 python3-pip git build-essential
```

For the Python synchronizer, install Mido if required:

```bash
python3 -m pip install mido
```

Use a virtual environment if your OS's Python packaging policy recommends it. The source files currently hard-code `/sdcard/Download/...` paths, which are Android-specific; change the paths for Raspberry Pi before running. The C++ source also hard-codes its base directory. Raspberry Pi compatibility is not guaranteed until tested.

## Official references

- **Termux app / source / installation:** https://github.com/termux/termux-app
- **Termux on F-Droid:** https://f-droid.org/en/packages/com.termux/
- **Termux package documentation:** https://github.com/termux/termux-packages
- **Mido Python MIDI library:** https://github.com/mido/mido
- **Mido documentation:** https://mido.readthedocs.io/
- **Raspberry Pi OS documentation:** https://www.raspberrypi.com/documentation/computers/os.html
- **Raspberry Pi Imager:** https://www.raspberrypi.com/software/

## License

**No project license was supplied with the reviewed source files.** Add a `LICENSE` file and specify the intended license before granting users permission to redistribute or modify the project. Until then, all rights remain with their respective copyright holders, subject to applicable law.

---

**Android-first • Termux-native workflow • MIDI timing tools • Black MIDI part concatenation**
