#!/usr/bin/env python3
"""
GPX Parser for Workout Dashboard
Parses GPX files in gpx/ directory, extracts workout data,
appends to data.json, and generates tracks.json for map display.
"""

import xml.etree.ElementTree as ET
import json
import os
import math
import re
from datetime import datetime

# Support both GPX 1.0 and 1.1 namespaces
GPX_NS = {
    'gpx1': 'http://www.topografix.com/GPX/1/0',
    'gpx': 'http://www.topografix.com/GPX/1/1',
}
# Garmin TrackPointExtension for heart rate
TPX_NS = {
    'tpx': 'http://www.garmin.com/xmlschemas/TrackPointExtension/v1',
    'tpx2': 'http://www.garmin.com/xmlschemas/TrackPointExtension/v2',
}

def parse_time(time_str):
    """Parse ISO 8601 time string to datetime."""
    if not time_str:
        return None
    time_str = time_str.strip()
    time_str = re.sub(r'\.\d+', '', time_str)
    time_str = time_str.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(time_str)
    except ValueError:
        return None


def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance in meters between two lat/lon points."""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def find_text(elem, paths, ns=None):
    """Try multiple paths to find text content."""
    for path in paths:
        if ns:
            el = elem.find(path, ns)
        else:
            el = elem.find(path)
        if el is not None and el.text:
            return el.text.strip()
    return None


def parse_gpx_file(filepath):
    """
    Parse a GPX file and extract workout data.
    Returns dict with: date, type, dist, pace, hr, min, gpxPoints
    """
    filename = os.path.basename(filepath)

    if 'train' in filename.lower():
        act_type = 'train'
    else:
        act_type = 'run'

    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    if date_match:
        act_date = date_match.group(1)
    else:
        mtime = os.path.getmtime(filepath)
        act_date = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')

    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except Exception as e:
        print(f"[WARN] Failed to parse {filename}: {e}")
        return None

    all_ns = [GPX_NS, {'gpx': GPX_NS['gpx1']}, {'gpx': GPX_NS['gpx']}, {}]

    track_points = []
    for ns in all_ns:
        pts = root.findall('.//gpx:trkpt', ns)
        if not pts:
            pts = root.findall('.//gpx:wpt', ns)
        if not pts:
            pts = root.findall('.//trkpt')
        if not pts:
            pts = root.findall('.//wpt')
        if pts:
            break

    if not pts:
        print(f"[WARN] No track points found in {filename}")
        return None

    parsed_points = []
    for pt in pts:
        try:
            lat = float(pt.get('lat'))
            lon = float(pt.get('lon'))
        except (TypeError, ValueError):
            continue

        time_elem = pt.find('gpx:time', ns) if ns else pt.find('time')
        if time_elem is None:
            time_elem = pt.find('.//time')
        t = parse_time(time_elem.text) if time_elem is not None else None

        hr = None
        for ext_path in ['gpx:extensions/gpx:hr',
                         'extensions/TrackPointExtension/hr',
                         './/hr',
                         './/HeartRate',
                         './/tpx:hr',
                         './/tpx2:hr']:
            hr_elem = pt.find(ext_path, {**GPX_NS, **TPX_NS}) if ':' in ext_path else pt.find(ext_path)
            if hr_elem is not None and hr_elem.text:
                try:
                    hr = int(float(hr_elem.text))
                    break
                except ValueError:
                    pass

        parsed_points.append({
            'lat': round(lat, 6),
            'lon': round(lon, 6),
            'time': t,
            'hr': hr,
        })

    if not parsed_points:
        print(f"[WARN] No valid points in {filename}")
        return None

    total_dist = 0.0
    for i in range(1, len(parsed_points)):
        total_dist += haversine(
            parsed_points[i - 1]['lat'], parsed_points[i - 1]['lon'],
            parsed_points[i]['lat'], parsed_points[i]['lon']
        )
    total_dist_km = round(total_dist / 1000, 2)

    times = [p['time'] for p in parsed_points if p['time'] is not None]
    if len(times) >= 2:
        duration_sec = abs((times[-1] - times[0]).total_seconds())
        duration_min = round(duration_sec / 60)
    else:
        duration_min = round(total_dist_km * 6) if total_dist_km > 0 else 0

    if total_dist_km > 0 and duration_min > 0:
        pace = round(duration_min / total_dist_km, 4)
    else:
        pace = 0

    hrs = [p['hr'] for p in parsed_points if p['hr'] is not None]
    avg_hr = round(sum(hrs) / len(hrs)) if hrs else 0

    gpx_points = [{'lat': p['lat'], 'lon': p['lon']} for p in parsed_points]

    if len(gpx_points) > 500:
        step = len(gpx_points) // 500
        gpx_points = gpx_points[::step] + [gpx_points[-1]]

    result = {
        'date': act_date,
        'type': act_type,
        'dist': total_dist_km,
        'pace': pace,
        'hr': avg_hr,
        'min': duration_min,
        'gpxPoints': gpx_points,
    }

    print(f"[OK] Parsed {filename}: {act_date} {act_type} {total_dist_km}km pace={pace} HR={avg_hr}")
    return result


def simplify_track(points, max_points=300):
    """Reduce number of track points to save space."""
    if len(points) <= max_points:
        return points
    step = len(points) // max_points
    return points[::step] + [points[-1]]


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    gpx_dir = os.path.join(repo_root, 'gpx')
    data_json = os.path.join(repo_root, 'data.json')
    tracks_json = os.path.join(repo_root, 'tracks.json')

    if not os.path.isdir(gpx_dir):
        print(f"[INFO] No gpx/ directory found, nothing to do.")
        return

    gpx_files = [f for f in os.listdir(gpx_dir) if f.lower().endswith('.gpx')]
    if not gpx_files:
        print(f"[INFO] No GPX files in gpx/ directory.")
        return

    print(f"[INFO] Found {len(gpx_files)} GPX file(s): {gpx_files}")

    if os.path.isfile(data_json):
        with open(data_json, 'r', encoding='utf-8-sig') as f:
            acts = json.load(f)
    else:
        acts = []

    existing_dates = {(a.get('date'), a.get('type')) for a in acts}

    if os.path.isfile(tracks_json):
        with open(tracks_json, 'r', encoding='utf-8-sig') as f:
            tracks = json.load(f)
    else:
        tracks = {}

    new_activities = []
    processed_files = []

    for gpx_file in sorted(gpx_files):
        filepath = os.path.join(gpx_dir, gpx_file)
        result = parse_gpx_file(filepath)
        if result is None:
            continue

        key = (result['date'], result['type'])
        if key in existing_dates:
            print(f"[SKIP] Duplicate: {result['date']} {result['type']}")
            processed_files.append(filepath)
            continue

        new_activities.append(result)
        existing_dates.add(key)

        tracks[result['date']] = {
            'type': result['type'],
            'dist': result['dist'],
            'track': [[p['lat'], p['lon']] for p in result['gpxPoints']],
        }

        processed_files.append(filepath)

    if not new_activities:
        print("[INFO] No new activities to add.")
        return

    acts.extend(new_activities)
    acts.sort(key=lambda a: a.get('date', ''))

    acts_to_save = []
    for a in acts:
        a_copy = {k: v for k, v in a.items() if k != 'gpxPoints'}
        acts_to_save.append(a_copy)

    with open(data_json, 'w', encoding='utf-8') as f:
        json.dump(acts_to_save, f, indent=2, ensure_ascii=False)
        f.write('\n')

    with open(tracks_json, 'w', encoding='utf-8') as f:
        json.dump(tracks, f, indent=2, ensure_ascii=False)
        f.write('\n')

    print(f"[OK] Added {len(new_activities)} activity(ies) to data.json")
    print(f"[OK] Updated tracks.json with {len(tracks)} track(s)")

    processed_dir = os.path.join(gpx_dir, 'processed')
    os.makedirs(processed_dir, exist_ok=True)
    for filepath in processed_files:
        fname = os.path.basename(filepath)
        dest = os.path.join(processed_dir, fname)
        if os.path.isfile(dest):
            base, ext = os.path.splitext(fname)
            dest = os.path.join(processed_dir, f"{base}_{int(datetime.now().timestamp())}{ext}")
        os.rename(filepath, dest)
        print(f"[OK] Moved {fname} to gpx/processed/")


if __name__ == '__main__':
    main()
