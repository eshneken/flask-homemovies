"""Check the combined existing/upload inventory without printing private names."""
import argparse
import bisect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python_app'))
from b2_media import MediaAccessError, media_kind


def validate_names(names):
    names = sorted(set(names))
    mp4_count = 0
    for name in names:
        if not name.lower().endswith('.mp4') or any(
                p.lower().endswith('.hls') for p in name.split('/')[:-1]):
            continue
        media_kind(name)
        mp4_count += 1
        index = bisect.bisect_right(names, name)
        if index < len(names) and names[index].startswith(name):
            raise MediaAccessError('An MP4 filename prefix matches another object. Do not upload.')
    return mp4_count


def candidate_names(source, prefix):
    if source.is_file():
        return [prefix]
    if not source.is_dir() or not prefix.endswith('/'):
        raise ValueError('Provide an existing file/exact key or a directory/trailing-slash prefix.')
    return [prefix + p.relative_to(source).as_posix() for p in source.rglob('*')
            if p.is_file() and p.name != '.DS_Store']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--existing', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--prefix', required=True)
    args = parser.parse_args(argv)
    try:
        existing = json.loads(args.existing.read_text())
        names = [row['fileName'] for row in existing]
        names.extend(candidate_names(args.source, args.prefix))
        count = validate_names(names)
        print(f'PASS: combined inventory has {count} standalone MP4 files and no prefix collisions.')
        return 0
    except Exception:
        print('FAIL: invalid inventory or MP4 prefix collision. Do not upload; private names suppressed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
