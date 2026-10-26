import os
import glob
import json
import math
from bisect import bisect_right
from collections import defaultdict, deque

import mido
from mido import MidiFile, MidiTrack, MetaMessage, Message


TARGET_BPM = 120.0
FIXED_VELOCITY = 90
PIANO_PROGRAM = 0
OUTPUT_CHANNEL = 0

ENABLE_BPM_LOCK = True
ENABLE_PIANO_MODE = True
ENABLE_FIXED_VELOCITY = True
ENABLE_CHANNEL_MAPPING = True
ENABLE_REMOVE_NON_NOTE_EVENTS = True
ENABLE_TEMPO_CLEANING = True
ENABLE_REPORT = True

INPUT_ROOT = "/sdcard/Download/midi_input"
OUTPUT_ROOT = "/sdcard/Download/midi_fixed"
REPORT_ROOT = "/sdcard/Download/midi_reports"

FOLDER_NAMES = ["folder_1", "folder_2", "folder_3"]

MIDI_MAX_TEMPO = 0xFFFFFF
MIDI_MAX_TICKS_PER_BEAT = 0x7FFF
DEFAULT_TEMPO = 500000


def clamp_velocity(value):
    return max(1, min(127, int(value)))


def clamp_program(value):
    return max(0, min(127, int(value)))


def get_effective_target_tempo(target_bpm):
    if not math.isfinite(float(target_bpm)) or float(target_bpm) <= 0:
        raise ValueError("TARGET_BPM must be a positive finite number.")
    requested_tempo = int(round(60000000.0 / float(target_bpm)))
    effective_tempo = max(1, min(MIDI_MAX_TEMPO, requested_tempo))
    return effective_tempo, mido.tempo2bpm(effective_tempo)


def build_tempo_map(mid):
    raw_events = []
    order = 0

    for track in mid.tracks:
        absolute_tick = 0
        for msg in track:
            absolute_tick += msg.time
            if msg.type == "set_tempo":
                raw_events.append((absolute_tick, order, int(msg.tempo)))
            order += 1

    raw_events.sort(key=lambda item: (item[0], item[1]))

    tempo_events = [(0, DEFAULT_TEMPO)]
    for tick, _, tempo in raw_events:
        if tick < 0:
            continue
        if tempo_events[-1][0] == tick:
            tempo_events[-1] = (tick, tempo)
        else:
            tempo_events.append((tick, tempo))

    ticks = [item[0] for item in tempo_events]
    tempos = [item[1] for item in tempo_events]
    elapsed_at_segment = [0.0] * len(tempo_events)

    for index in range(1, len(tempo_events)):
        previous_tick = ticks[index - 1]
        current_tick = ticks[index]
        previous_tempo = tempos[index - 1]
        elapsed_at_segment[index] = (
            elapsed_at_segment[index - 1]
            + (current_tick - previous_tick)
            * previous_tempo
            / mid.ticks_per_beat
        )

    def microseconds_at_tick(target_tick):
        index = bisect_right(ticks, target_tick) - 1
        if index < 0:
            index = 0
        return (
            elapsed_at_segment[index]
            + (target_tick - ticks[index]) * tempos[index] / mid.ticks_per_beat
        )

    return raw_events, tempo_events, microseconds_at_tick


def collect_events(mid, report):
    events = []
    order = 0
    active_notes = defaultdict(deque)
    matched_pairs = []

    for track in mid.tracks:
        absolute_tick = 0
        for msg in track:
            absolute_tick += msg.time

            if msg.type == "set_tempo":
                report["original_tempo_events"] += 1
                if ENABLE_BPM_LOCK and ENABLE_TEMPO_CLEANING:
                    report["tempo_events_removed"] += 1
                    order += 1
                    continue

            if msg.type == "end_of_track":
                order += 1
                continue

            if msg.is_meta:
                if ENABLE_REMOVE_NON_NOTE_EVENTS:
                    report["non_note_events_removed"] += 1
                    order += 1
                    continue
                events.append((absolute_tick, 3, order, msg.copy(time=0)))
                order += 1
                continue

            if msg.type in ("note_on", "note_off"):
                source_channel = msg.channel
                note_key = (source_channel, msg.note)
                is_note_on = msg.type == "note_on" and msg.velocity > 0

                if is_note_on:
                    report["notes_detected"] += 1
                    active_notes[note_key].append(absolute_tick)

                    velocity = (
                        clamp_velocity(FIXED_VELOCITY)
                        if ENABLE_FIXED_VELOCITY
                        else msg.velocity
                    )
                    if ENABLE_FIXED_VELOCITY:
                        report["notes_velocity_normalized"] += 1
                    if ENABLE_PIANO_MODE:
                        report["notes_forced_to_piano"] += 1

                    output_channel = (
                        OUTPUT_CHANNEL if ENABLE_CHANNEL_MAPPING else source_channel
                    )
                    copied = msg.copy(
                        channel=output_channel,
                        velocity=velocity,
                        time=0
                    )
                    events.append((absolute_tick, 1, order, copied))
                else:
                    if active_notes[note_key]:
                        start_tick = active_notes[note_key].popleft()
                        matched_pairs.append((start_tick, absolute_tick))
                        report["notes_preserved"] += 1
                    else:
                        report["notes_unmatched"] += 1

                    output_channel = (
                        OUTPUT_CHANNEL if ENABLE_CHANNEL_MAPPING else source_channel
                    )
                    copied = msg.copy(channel=output_channel, time=0)
                    events.append((absolute_tick, 0, order, copied))

                order += 1
                continue

            if ENABLE_REMOVE_NON_NOTE_EVENTS:
                report["non_note_events_removed"] += 1
                order += 1
                continue

            copied = msg.copy(time=0)
            if ENABLE_CHANNEL_MAPPING and hasattr(copied, "channel"):
                copied.channel = OUTPUT_CHANNEL
            events.append((absolute_tick, 3, order, copied))
            order += 1

    for starts in active_notes.values():
        report["notes_unmatched"] += len(starts)

    return events, matched_pairs


def process_midi_file(input_path, output_path):
    report = {
        "file": os.path.basename(input_path),
        "status": "FAILED",
        "input_ticks_per_beat": None,
        "output_ticks_per_beat": None,
        "input_tracks": 0,
        "output_tracks": 1,
        "requested_target_bpm": TARGET_BPM,
        "effective_target_bpm": None,
        "target_program": PIANO_PROGRAM,
        "output_channel": OUTPUT_CHANNEL,
        "notes_detected": 0,
        "notes_modified": 0,
        "notes_preserved": 0,
        "notes_unmatched": 0,
        "notes_forced_to_piano": 0,
        "notes_velocity_normalized": 0,
        "non_note_events_removed": 0,
        "tempo_events_removed": 0,
        "original_tempo_events": 0,
        "total_original_note_beats": 0.0,
        "total_output_note_beats": 0.0,
        "maximum_original_note_beats": 0.0,
        "maximum_output_note_beats": 0.0,
        "errors": []
    }

    try:
        mid = MidiFile(input_path)
        if mid.ticks_per_beat <= 0:
            raise ValueError("Invalid MIDI ticks_per_beat value.")

        report["input_ticks_per_beat"] = mid.ticks_per_beat
        report["input_tracks"] = len(mid.tracks)

        raw_tempo_events, tempo_map, microseconds_at_tick = build_tempo_map(mid)
        report["original_tempo_events"] = len(raw_tempo_events)

        target_tempo, effective_bpm = get_effective_target_tempo(TARGET_BPM)
        report["effective_target_bpm"] = round(effective_bpm, 6)

        if ENABLE_BPM_LOCK:
            initial_source_tempo = tempo_map[0][1]
            desired_tpb = int(round(
                mid.ticks_per_beat * target_tempo / initial_source_tempo
            ))
            output_tpb = max(1, min(MIDI_MAX_TICKS_PER_BEAT, desired_tpb))
        else:
            output_tpb = mid.ticks_per_beat

        report["output_ticks_per_beat"] = output_tpb

        events, matched_pairs = collect_events(mid, report)

        output_ticks_for_source_tick = {}

        def map_tick(source_tick):
            if source_tick not in output_ticks_for_source_tick:
                if ENABLE_BPM_LOCK:
                    real_time_us = microseconds_at_tick(source_tick)
                    exact_tick = real_time_us * output_tpb / target_tempo
                    output_ticks_for_source_tick[source_tick] = max(
                        0, int(round(exact_tick))
                    )
                else:
                    output_ticks_for_source_tick[source_tick] = source_tick
            return output_ticks_for_source_tick[source_tick]

        for start_tick, end_tick in matched_pairs:
            original_beats = (end_tick - start_tick) / mid.ticks_per_beat
            output_beats = (map_tick(end_tick) - map_tick(start_tick)) / output_tpb
            report["total_original_note_beats"] += original_beats
            report["total_output_note_beats"] += output_beats
            report["maximum_original_note_beats"] = max(
                report["maximum_original_note_beats"], original_beats
            )
            report["maximum_output_note_beats"] = max(
                report["maximum_output_note_beats"], output_beats
            )

        mapped_events = []
        for source_tick, priority, original_order, msg in events:
            mapped_events.append((
                map_tick(source_tick),
                priority,
                original_order,
                msg
            ))

        if ENABLE_BPM_LOCK:
            mapped_events.append((
                0,
                -2,
                -2,
                MetaMessage("set_tempo", tempo=target_tempo, time=0)
            ))

        if ENABLE_PIANO_MODE:
            mapped_events.append((
                0,
                -1,
                -1,
                Message(
                    "program_change",
                    channel=OUTPUT_CHANNEL,
                    program=clamp_program(PIANO_PROGRAM),
                    time=0
                )
            ))

        mapped_events.sort(key=lambda item: (item[0], item[1], item[2]))

        out_mid = MidiFile(type=0, ticks_per_beat=output_tpb)
        out_track = MidiTrack()
        out_mid.tracks.append(out_track)

        last_tick = 0
        for absolute_tick, _, _, msg in mapped_events:
            delta = absolute_tick - last_tick
            if delta < 0:
                raise ValueError("Event timeline became negative after conversion.")
            out_track.append(msg.copy(time=delta))
            last_tick = absolute_tick

        out_track.append(MetaMessage("end_of_track", time=0))

        output_parent = os.path.dirname(output_path)
        if output_parent:
            os.makedirs(output_parent, exist_ok=True)
        out_mid.save(output_path)

        report["status"] = "SUCCESS"

    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")

    return report


def process_folder(folder_name):
    input_dir = os.path.join(INPUT_ROOT, folder_name)
    output_dir = os.path.join(OUTPUT_ROOT, folder_name)
    report_dir = os.path.join(REPORT_ROOT, folder_name)

    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(report_dir, exist_ok=True)

    midi_files = sorted(
        glob.glob(os.path.join(input_dir, "*.mid"))
        + glob.glob(os.path.join(input_dir, "*.midi"))
        + glob.glob(os.path.join(input_dir, "*.MID"))
        + glob.glob(os.path.join(input_dir, "*.MIDI"))
    )

    folder_report = {
        "folder": folder_name,
        "files_found": len(midi_files),
        "files_success": 0,
        "files_failed": 0,
        "notes_detected": 0,
        "notes_modified": 0,
        "notes_preserved": 0,
        "notes_unmatched": 0,
        "notes_forced_to_piano": 0,
        "notes_velocity_normalized": 0,
        "non_note_events_removed": 0,
        "tempo_events_removed": 0,
        "files": []
    }

    for input_path in midi_files:
        file_name = os.path.basename(input_path)
        output_path = os.path.join(output_dir, file_name)
        report = process_midi_file(input_path, output_path)
        folder_report["files"].append(report)

        for key in (
            "notes_detected",
            "notes_modified",
            "notes_preserved",
            "notes_unmatched",
            "notes_forced_to_piano",
            "notes_velocity_normalized",
            "non_note_events_removed",
            "tempo_events_removed"
        ):
            folder_report[key] += report.get(key, 0)

        if report["status"] == "SUCCESS":
            folder_report["files_success"] += 1
            print(f"[SUCCESS] {folder_name}/{file_name}")
        else:
            folder_report["files_failed"] += 1
            print(f"[FAILED] {folder_name}/{file_name}")
            for error in report["errors"]:
                print(f"  {error}")

    if folder_report["files_found"] == 0:
        folder_report["status"] = "EMPTY"
    elif folder_report["files_failed"] == 0:
        folder_report["status"] = "SUCCESS"
    else:
        folder_report["status"] = "PARTIAL"

    if ENABLE_REPORT:
        report_path = os.path.join(report_dir, "folder_report.json")
        with open(report_path, "w", encoding="utf-8") as file:
            json.dump(folder_report, file, indent=2, ensure_ascii=False)

    return folder_report


def create_global_report(folder_reports):
    totals = {
        "files_found": 0,
        "files_success": 0,
        "files_failed": 0,
        "notes_detected": 0,
        "notes_modified": 0,
        "notes_preserved": 0,
        "notes_unmatched": 0,
        "notes_forced_to_piano": 0,
        "notes_velocity_normalized": 0,
        "non_note_events_removed": 0,
        "tempo_events_removed": 0
    }

    for report in folder_reports:
        for key in totals:
            totals[key] += report.get(key, 0)

    return {
        "configuration": {
            "requested_target_bpm": TARGET_BPM,
            "fixed_velocity": FIXED_VELOCITY,
            "piano_program": PIANO_PROGRAM,
            "output_channel": OUTPUT_CHANNEL,
            "bpm_lock": ENABLE_BPM_LOCK,
            "piano_mode": ENABLE_PIANO_MODE,
            "fixed_velocity_mode": ENABLE_FIXED_VELOCITY,
            "channel_mapping": ENABLE_CHANNEL_MAPPING,
            "remove_non_note_events": ENABLE_REMOVE_NON_NOTE_EVENTS,
            "tempo_cleaning": ENABLE_TEMPO_CLEANING,
            "duration_cap": False
        },
        "folders": folder_reports,
        "totals": totals
    }


def print_report(folder_reports, global_report):
    totals = global_report["totals"]

    print()
    print("=" * 60)
    print("MIDI MASTER SYNCHRONIZER + PIANO PROCESSOR")
    print("=" * 60)
    print(f"Requested target BPM: {TARGET_BPM}")
    print(f"Fixed velocity: {FIXED_VELOCITY}")
    print(f"Piano mode: {'ON' if ENABLE_PIANO_MODE else 'OFF'}")
    print(f"BPM lock: {'ON' if ENABLE_BPM_LOCK else 'OFF'}")
    print("Note duration modification: OFF")
    print()

    for report in folder_reports:
        print(f"[{report['folder']}]")
        print(f"Files: {report['files_success']}/{report['files_found']}")
        print(f"Notes detected: {report['notes_detected']}")
        print(f"Paired notes preserved: {report['notes_preserved']}")
        print(f"Unmatched note events: {report['notes_unmatched']}")
        print()

    print("-" * 60)
    print("GLOBAL TOTAL")
    print(f"Files: {totals['files_success']}/{totals['files_found']}")
    print(f"Notes detected: {totals['notes_detected']}")
    print(f"Paired notes preserved: {totals['notes_preserved']}")
    print(f"Unmatched note events: {totals['notes_unmatched']}")
    print("=" * 60)


def main():
    os.makedirs(INPUT_ROOT, exist_ok=True)
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    os.makedirs(REPORT_ROOT, exist_ok=True)

    print("=" * 60)
    print("MIDI MASTER SYNCHRONIZER + PIANO PROCESSOR")
    print("=" * 60)
    print(f"Requested target BPM: {TARGET_BPM}")
    print(f"Input: {INPUT_ROOT}")
    print(f"Output: {OUTPUT_ROOT}")
    print(f"Reports: {REPORT_ROOT}")

    folder_reports = []
    for folder_name in FOLDER_NAMES:
        print()
        print(f"Processing folder: {folder_name}")
        folder_reports.append(process_folder(folder_name))

    global_report = create_global_report(folder_reports)

    if ENABLE_REPORT:
        report_path = os.path.join(REPORT_ROOT, "global_report.json")
        with open(report_path, "w", encoding="utf-8") as file:
            json.dump(global_report, file, indent=2, ensure_ascii=False)

    print_report(folder_reports, global_report)


if __name__ == "__main__":
    main()
