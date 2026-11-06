"""ABC Electronics 내부 직원용 데이터 관리 화면."""

import json
import sys
from pathlib import Path

# database 패키지와 database/database.py 이름 충돌 방지
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)

if PROJECT_ROOT in sys.path:
    sys.path.remove(PROJECT_ROOT)

sys.path.insert(0, PROJECT_ROOT)

import streamlit as st

from database.extract import discover_files
from database.pipeline import (
    build_preview,
    commit_preview,
    pending_archives,
    retry_archiving
)


st.set_page_config(
    page_title='ABC Electronics | 데이터 관리',
    layout='wide'
)

st.title('ABC Electronics | 데이터 관리')

st.caption(
    'inbox 파일 탐색 → DB 비교 → 변경사항 확인 → '
    '관리자 승인 → DB 저장 → archive 보관'
)


# --------------------------------------------------
# 1. 보관 미완료 작업 확인
# --------------------------------------------------

pending = pending_archives()

if pending:
    st.warning(
        f'이전 DB 저장은 성공했지만 파일 보관이 '
        f'미완료된 작업이 {len(pending)}건 있습니다.'
    )

    if st.button('완료된 파일의 archive 이동 재시도'):
        output = retry_archiving()

        if output['errors']:
            st.error('\n'.join(output['errors']))
        else:
            st.success('보관 완료')

        st.rerun()


# --------------------------------------------------
# 2. 신규 입력 파일 확인
# --------------------------------------------------

with st.expander(
    '처리 대기 중인 로컬 파일',
    expanded=True
):
    try:
        found = discover_files()
        total = sum(len(paths) for paths in found.values())

        if not total:
            st.info(
                'inbox가 비어 있습니다. '
                '신규 PDF 또는 판매 Excel을 해당 폴더에 넣으세요.'
            )

        for folder, paths in found.items():
            st.markdown(
                f'**{folder}** — {len(paths)}개'
            )

            for path in paths:
                st.text(path.name)

    except Exception as exc:
        st.error(str(exc))


# --------------------------------------------------
# 3. 신규 파일 분석
# --------------------------------------------------

if st.button(
    '1. 신규 파일 분석 및 DB 변경사항 미리보기',
    type='primary',
    disabled=bool(pending)
):
    st.session_state.pop('preview', None)
    st.session_state.pop('approved', None)
    st.session_state.pop('last_result', None)

    try:
        with st.spinner(
            '원본을 읽고 기존 PostgreSQL 데이터와 비교합니다...'
        ):
            st.session_state['preview'] = build_preview()

        st.success(
            '분석 완료. 아직 DB에 저장하거나 '
            '파일을 이동하지 않았습니다.'
        )

    except Exception as exc:
        st.error(f'분석 실패: {exc}')


# --------------------------------------------------
# 4. 최근 저장 결과
# --------------------------------------------------

if 'last_result' in st.session_state:
    result = st.session_state['last_result']

    if result['db_saved']:
        st.success('PostgreSQL 저장에 성공했습니다.')

    if result['archive_pending']:
        st.warning(
            '원본 파일 보관이 완료되지 않았습니다. '
            '위에서 archive 이동을 재시도하세요.'
        )

        for error in result['archive_errors']:
            st.error(error)

    else:
        st.info('처리 대상 원본을 archive로 이동했습니다.')

    with st.expander('최근 저장 결과'):
        st.json(result['result'])


# --------------------------------------------------
# 5. 데이터 미리보기 및 DB 저장
# --------------------------------------------------

preview = st.session_state.get('preview')

if preview:
    review = preview['review']

    st.subheader('검증 결과')

    if review['ready_to_save']:
        st.success('검증 통과')
    else:
        st.error('검증 실패: 저장할 수 없습니다.')

    for err in review['errors']:
        st.error(err)

    for warning in review['warnings']:
        st.caption(warning)

    # 변경사항 요약
    st.subheader('변경사항 요약')

    change_table = []

    for table, stats in review['changes'].items():
        change_table.append({
            '대상': table,
            '신규': len(stats['insert']),
            '수정': len(stats['update']),
            '변경 없음': len(stats['skip']),
            '삭제/관계 해제': len(stats['delete'])
        })

    st.dataframe(
        change_table,
        use_container_width=True,
        hide_index=True
    )

    st.caption(
        '삭제는 변경된 설명서의 오래된 청크와 '
        '카드할인 정책의 해제된 연결에만 적용됩니다. '
        '기존 상품·재고·판매 데이터는 자동으로 삭제하지 않습니다.'
    )

    # 변환 결과 조회
    st.subheader('데이터 확인')

    target = st.selectbox(
        'RDB 테이블',
        list(preview['rdb'])
    )

    st.dataframe(
        preview['rdb'][target][:30],
        use_container_width=True,
        hide_index=True
    )

    with st.expander('설명서 내용 일부'):
        for c in preview['vector_db']['chunks'][:3]:
            st.markdown(
                f'**{c["product_name"]}** ({c["product_id"]}) — '
                f'{c["metadata"]["source_file"]}, '
                f'{c["metadata"]["page_number"]}쪽'
            )

            st.text(c['content'][:600])

    st.download_button(
        '미리보기 JSON 다운로드',
        data=json.dumps(
            preview,
            ensure_ascii=False,
            indent=2
        ),
        file_name='import_preview.json',
        mime='application/json'
    )

    # 승인 및 저장
    st.divider()
    st.subheader('2. DB에 저장')

    st.warning(
        '저장하면 PostgreSQL 데이터가 실제로 변경됩니다. '
        '성공한 원본 파일은 archive로 이동합니다.'
    )

    st.checkbox(
        '변경 내용을 확인했으며 DB 저장에 동의합니다.',
        key='approved'
    )

    can_save = bool(
        review['ready_to_save']
        and st.session_state.get('approved')
    )

    if st.button(
        '승인하고 PostgreSQL에 저장',
        type='primary',
        disabled=not can_save
    ):
        try:
            with st.spinner(
                '필요한 설명서만 임베딩하고 DB에 저장합니다...'
            ):
                result = commit_preview(preview)

            st.session_state['last_result'] = result
            st.session_state.pop('preview', None)

            st.rerun()

        except Exception as exc:
            st.error(f'저장 실패: {exc}')
            st.caption(
                'DB 저장 전 실패라면 원본은 inbox에 남습니다. '
                'DB 저장 후 보관 실패라면 DB가 이미 변경됐을 수 있으므로 '
                '처리 이력을 확인하세요.'
            )


# --------------------------------------------------
# 6. 등록된 제품 이미지 조회
# --------------------------------------------------

with st.expander(
    'DB에 등록된 제품 이미지 확인',
    expanded=False
):
    from database.images import DATA_DIR, IMAGES_DIR

    if st.button('제품 이미지 목록 불러오기'):
        try:
            from database.database import _connection

            with _connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        SELECT
                            product_id,
                            product_name,
                            brand,
                            product_image_path
                        FROM public.products
                        WHERE product_image_path IS NOT NULL
                        ORDER BY brand, product_name
                    ''')

                    st.session_state['db_product_images'] = (
                        cur.fetchall()
                    )

        except Exception as exc:
            st.error(f'이미지 목록 조회 실패: {exc}')

    stored_images = st.session_state.get(
        'db_product_images', []
    )

    if stored_images:
        st.caption(
            f'이미지 경로가 등록된 상품: '
            f'{len(stored_images)}개'
        )

        choices = {
            f'{row["brand"]} · {row["product_name"]} '
            f'({row["product_id"]})': row
            for row in stored_images
        }

        selected = st.selectbox(
            '상품 선택',
            list(choices)
        )

        row = choices[selected]
        relative_path = row['product_image_path']

        image_path = (
            DATA_DIR / relative_path
        ).resolve()

        if not image_path.is_relative_to(IMAGES_DIR.resolve()):
            st.error('허용되지 않은 이미지 저장 경로입니다.')

        elif image_path.is_file():
            st.image(
                str(image_path),
                caption=(
                    f'{row["product_name"]} — '
                    f'{relative_path}'
                ),
                width=350
            )

        else:
            st.error(
                f'DB 경로는 있지만 파일이 없습니다: '
                f'{relative_path}'
            )

    elif 'db_product_images' in st.session_state:
        st.info(
            'DB에 이미지 경로가 등록된 상품이 없습니다.'
        )


st.caption(
    'Docker 실행: docker compose up -d --build app '
    '| http://localhost:8501'
)