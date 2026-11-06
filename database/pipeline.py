"""파일 추출 -> DB 대조·검증 -> 미리보기 -> 승인 후 DB 저장 -> 원본 보관."""

import json
from datetime import datetime
from pathlib import Path
from shutil import move
from uuid import uuid4

from database.extract import RAW, discover_files, extract_all, manifest_matches
from database.transform import make_preview
from database.database import load_state, save_all
from database.images import materialize_preview_images


BASE = Path(__file__).resolve().parent
PROCESSED = BASE / 'data' / 'processed'

PREVIEW_PATH = PROCESSED / 'import_preview.json'
HISTORY_PATH = PROCESSED / 'import_history.json'
SNAPSHOTS_DIR = PROCESSED / 'snapshots'
ARCHIVE_DIR = BASE / 'data' / 'archive'


def _read_history():
    if not HISTORY_PATH.exists():
        return []

    result = json.loads(HISTORY_PATH.read_text(encoding='utf-8'))

    if not isinstance(result, list):
        raise ValueError('import_history.json의 형식이 잘못되었습니다.')

    return result


def _write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_name(path.name + '.tmp')

    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
        encoding='utf-8'
    )

    temporary.replace(path)


def pending_archives():
    return [
        item for item in _read_history()
        if item['status'] == 'archive_pending'
    ]


def build_preview():
    """신규 파일 분석 및 JSON 저장. DB는 변경하지 않음."""

    if pending_archives():
        raise RuntimeError(
            '이전 DB 저장에 대한 파일 보관이 미완료입니다. '
            '먼저 보관 재시도를 실행하세요.'
        )

    inputs = discover_files()
    extracted = extract_all(inputs)

    state = load_state()
    preview = make_preview(extracted, state)

    # 분석별 고유 ID 생성
    run_id = (
        datetime.now().astimezone().strftime('%Y%m%d_%H%M%S_%f')
        + '_'
        + uuid4().hex[:8]
    )

    preview['review']['run_id'] = run_id

    # 과거 분석 결과 누적 보관
    _write_json_atomic(
        SNAPSHOTS_DIR / f'{run_id}.json',
        preview
    )

    # 최신 미리보기 갱신
    _write_json_atomic(PREVIEW_PATH, preview)

    return preview


def _archive_one(item):
    kind = item['kind']
    filename = item['name']
    fingerprint = item['sha256']

    if kind not in {'catalogs', 'manuals', 'sales'}:
        raise ValueError(f'허용되지 않은 폴더 종류: {kind}')

    src = RAW / kind / filename
    folder = ARCHIVE_DIR / kind

    folder.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        # 파일 이동은 성공했으나 이력 저장이 실패한 경우 복구
        from hashlib import sha256

        for candidate in folder.iterdir():
            if (
                candidate.is_file()
                and sha256(candidate.read_bytes()).hexdigest() == fingerprint
            ):
                return str(candidate.relative_to(BASE))

        raise FileNotFoundError(
            f'보관할 원본을 찾지 못했습니다: {src}'
        )

    from hashlib import sha256

    if sha256(src.read_bytes()).hexdigest() != fingerprint:
        raise ValueError(
            f'원본 내용이 변경돼 보관할 수 없습니다: {filename}'
        )

    dst = folder / filename

    if dst.exists():
        if sha256(dst.read_bytes()).hexdigest() == fingerprint:
            # 동일 파일이 이미 archive에 있는 경우
            src.unlink()
            return str(dst.relative_to(BASE))

        dst = folder / (
            f'{src.stem}_'
            f'{datetime.now():%Y%m%d_%H%M%S}_'
            f'{fingerprint[:8]}{src.suffix}'
        )

    move(str(src), str(dst))

    return str(dst.relative_to(BASE))


def retry_archiving():
    """DB 저장이 완료된 파일의 archive 이동 재시도."""

    history = _read_history()
    finished = 0
    errors = []

    for job in history:
        if job['status'] != 'archive_pending':
            continue

        for item in job['files']:
            token = f"{item['kind']}/{item['name']}"

            if token in job['archived']:
                continue

            try:
                job['archived'][token] = _archive_one(item)
                _write_json_atomic(HISTORY_PATH, history)

            except Exception as exc:
                errors.append(f'{token}: {exc}')

        if len(job['archived']) == len(job['files']):
            job['status'] = 'done'
            job['finished_at'] = (
                datetime.now().astimezone().isoformat()
            )

            finished += 1
            _write_json_atomic(HISTORY_PATH, history)

    return {
        'completed_batches': finished,
        'errors': errors,
        'pending_batches': len(pending_archives())
    }


def commit_preview(preview):
    """승인된 데이터 DB 저장 후 원본 파일 보관."""

    if pending_archives():
        raise RuntimeError(
            '이전 파일의 보관을 먼저 완료하세요.'
        )

    review = preview['review']

    if not review['ready_to_save']:
        raise ValueError(
            '검증 실패 데이터는 저장할 수 없습니다.'
        )

    if not manifest_matches(review['source_files']):
        raise ValueError(
            '미리보기 이후 inbox 파일이 추가·삭제·변경되었습니다. '
            '다시 분석하세요.'
        )

    # 승인된 제품 이미지 저장
    materialize_preview_images(
        review.get('image_manifest', [])
    )

    # PostgreSQL에 실제 데이터 저장
    result = save_all(preview)

    # DB 저장 성공 이력 기록
    history = _read_history()

    job = {
        'started_at': datetime.now().astimezone().isoformat(),
        'status': 'archive_pending',
        'files': review['source_files'],
        'archived': {},
        'result': result,

        # 해당 작업의 JSON과 연결
        'run_id': review.get('run_id'),
        'snapshot_path': (
            f'snapshots/{review["run_id"]}.json'
            if review.get('run_id')
            else None
        )
    }

    history.append(job)

    try:
        _write_json_atomic(HISTORY_PATH, history)

    except Exception as exc:
        return {
            'db_saved': True,
            'archive_pending': True,
            'result': result,
            'archive_errors': [
                f'처리 이력 기록 실패: {exc}. '
                'DB 저장은 이미 완료됨.'
            ]
        }

    # 저장 완료 원본을 archive로 이동
    archive_result = retry_archiving()

    return {
        'db_saved': True,
        'archive_pending': bool(
            archive_result['pending_batches']
        ),
        'archive_errors': archive_result['errors'],
        'result': result
    }


if __name__ == '__main__':
    preview = build_preview()

    print('미리보기:', PREVIEW_PATH)
    print('입력 파일:', len(preview['review']['source_files']))
    print('건수:', preview['review']['counts'])

    print(
        '검증:',
        '통과' if preview['review']['ready_to_save'] else '실패'
    )

    for error in preview['review']['errors']:
        print('오류:', error)

    print(
        '명령행 실행은 DB에 저장하거나 '
        '파일을 이동하지 않습니다.'
    )