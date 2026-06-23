# 민생100일 지표 대시보드

부산 민생100일 대시보드의 경제지표 영역을 별도 서비스로 운영하기 위한 초기 프로젝트 구조다.

운영 서버 배포 기준 경로:

```text
/opt/minsaeng100
```

권장 운영 방식:

- 기존 `/opt/busan`, `/opt/advisor` 서비스와 코드, DB, 가상환경, systemd unit을 분리한다.
- 화면은 외부 API를 직접 호출하지 않고 내부 DB를 조회한다.
- KOSIS/ECOS/행안부 데이터는 배치로 수집하고, 부산신용보증재단/정책자금 실적은 관리자 수동 입력 엑셀 또는 CSV 업로드로 관리한다.
- 금액 원자료는 원 단위로 저장하고, 화면에서는 억원 단위로 표시한다.
- 비교 표출은 같은 지표의 `부산 최신값`, `직전기간 부산값`, `전국/전체 기준값`을 DB에 함께 저장한 뒤 화면에서 계산한다.

## 로컬 실행

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py
python scripts/collect_all.py
uvicorn api.main:app --host 127.0.0.1 --port 8010
streamlit run dashboard/app.py --server.port 8510 --server.address 127.0.0.1
```

KOSIS 지표까지 수집하려면 서버 환경변수에 KOSIS OpenAPI 인증키를 설정한다.

```bash
export KOSIS_API_KEY="발급받은_KOSIS_인증키"
python scripts/collect_all.py
```

KOSIS 수집 대상은 소상공인·전통시장 BSI, 소비자심리지수, 고용률, 실업률, 소비자물가지수, 부산 동행종합지수다. 수집 결과는 `observations`에 저장되며, 화면은 같은 지표의 부산값·직전기간값·전국/전체값을 자동 계산해 표시한다.

## 주요 폴더

```text
api/                 FastAPI API
dashboard/           Streamlit 지표 화면
config/              지표 카탈로그
database/            SQLite 스키마
scripts/             초기화/수동 엑셀·CSV 적재 스크립트
data/manual/         수동 입력 템플릿
deploy/systemd/      systemd unit 초안
deploy/nginx/        nginx route 초안
docs/                운영/지표 설계 문서
```

## 현재 구현 범위

- 지표 카탈로그 정리
- SQLite 스키마
- 수동 입력 엑셀 템플릿 및 CSV 템플릿
- 카탈로그/최신값 조회 API
- Streamlit 대시보드 기본 화면
- 부산시 Big-데이터웨이브 카드소비액 및 Nowcast 카드 변동률 수집기
- 직전기간 증감 및 전국/전체 기준값 비교 표출
- systemd/nginx 배포 초안

아직 구현하지 않은 범위:

- KOSIS OpenAPI 일부 지표 파라미터 추가 검증
- 행안부 인허가정보 실제 수집기
- 관리자 로그인/권한
- 파일 업로드 화면
- 실서버 배포 및 nginx 적용
