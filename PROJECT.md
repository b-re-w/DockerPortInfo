# PROJECT — DockerPortInfo 설계 문서

## 1. 배경 / 문제

연구실에는 GPU 서버 2대(**primary**, **secondary**)가 있고, 각 서버는 Backend.ai를 런처로 사용해
Docker 컨테이너 세션을 띄워 그 안의 GPU를 사용한다. Backend.ai에서 포트를 설정하면 `docker ps`의
`PORTS` 컬럼에 `호스트IP:호스트포트->컨테이너포트/proto` 형태로 무작위(예: 30720번대) 호스트 포트가
매핑되어 나온다. 어떤 컨테이너의 어떤 내부 포트가 어느 호스트 포트로 열렸는지, 그리고 그 컨테이너의
런타임(python/ubuntu/cuda)이 무엇인지 매번 `docker ps`를 길게 읽어 확인하기 번거롭다.

이를 **한 화면에서 보기 좋게** 정리해 보여주는 것이 목표다.

## 2. 목표

- `docker ps` 출력에서 `cr.backend.ai` 이미지를 식별한다.
- 이미지 태그 `3.12-ubuntu24.04-cuda12.6.1` →  `python 3.12`, `ubuntu 24.04`, `cuda 12.6` 으로 표기.
- 포트 매핑을 `컨테이너 포트 → 호스트 포트` 형태(예: `8180 → 30726`)로 표기.
- primary/secondary 두 서버 모두를 한 페이지에서 본다.
- 화면은 1분마다 자동 갱신한다.

## 3. 아키텍처

- **웹 서버**: primary 서버에서 **user 권한**으로 실행되는 FastAPI 앱.
  - 수신 API `POST /docker/{server_name}/` — `docker ps` 원본 텍스트를 받는다.
  - 조회 API `GET /docker/{server_name}/`, `GET /api/snapshots` — 정리된 자료형을 JSON으로 반환.
  - 페이지 `GET /` — 정적 HTML/CSS/JS.
- **수집기**: primary/secondary 각각의 crontab이 1분마다 `send_docker_ps.sh`를 실행해
  `docker ps` 결과를 웹 서버로 POST 한다. (`docker ps`는 sudo 불필요 가정)
- **저장**: 웹 서버는 서버명을 키로 최신 스냅샷(`ServerSnapshot`)만 보관한다.
  인메모리 dict + 디스크(`data/<server>.json`) 영속화로 리로드/재시작 후에도 마지막 값을 복원한다.
- **프론트엔드**: 렌더 후 `setInterval`로 1분마다 `/api/snapshots`를 폴링해 화면을 다시 그린다.

```
[primary]   crontab(1m) ─ send_docker_ps.sh ─ docker ps ─┐
                                                          ├─POST /docker/<name>/─▶ FastAPI(primary) ─ store(메모리+디스크)
[secondary] crontab(1m) ─ send_docker_ps.sh ─ docker ps ─┘                              │
                                                                                        ▼
                                                              브라우저 ─GET /api/snapshots(1m 폴링)─ 화면 갱신
```

## 4. 데이터 모델 (`src/models.py`)

- `PortMapping`: `container_port`, `host_port`, `host_ip`, `proto`, `raw`
- `ImageInfo`: `raw_image`, `repo`, `raw_tag`, `is_backendai`, `language`, `language_version`, `ubuntu`, `cuda`, `cuda_full`
- `ContainerInfo`: `container_id`, `names`, `command`, `created`, `status`, `image`, `ports[]`, `raw_ports`
- `ServerSnapshot`: `server_name`, `updated_at`, `container_count`, `backendai_count`, `containers[]`, `raw?`

## 5. 파싱 전략 (`src/parser.py`)

기본 `docker ps` 출력은 **고정폭 컬럼**(헤더 기준 좌측 정렬 + 공백 패딩)이다.
`COMMAND`/`PORTS`처럼 공백·콤마가 섞인 컬럼을 단순 split으로 자르면 깨지므로:

1. 헤더 라인(`CONTAINER ID … NAMES`)을 찾아 각 컬럼명의 **시작 문자 offset**을 구한다.
2. 데이터 라인을 그 offset 구간으로 **슬라이싱**해 컬럼 값을 추출한다.
3. `IMAGE`는 마지막 `/` 이후의 `:`를 태그 구분자로 보고 repo/tag 분리 → 정규식으로
   `python 버전`, `ubuntu(\d+\.\d+)`, `cuda(\d+\.\d+)` 추출 (cuda는 major.minor만 표기).
4. `PORTS`는 `, `로 분리 후 `IP:HOST->CONTAINER/proto` 또는 `CONTAINER/proto`(노출만) 패턴 매칭.

이 방식은 IPv6 표기(`[::]`), 포트 범위(`9000-9001`), 매핑 없는 노출 포트(`2380/tcp`)를 모두 처리한다.

## 6. 운영 (`scripts/`)

- `launch_server.sh` (primary, crontab keepalive):
  - `pgrep -f "uvicorn.*src.app:app"`로 이미 떠 있으면 즉시 종료(중복 방지).
  - 죽어 있으면 `uv run uvicorn … --reload --reload-dir src`로 백그라운드 기동.
  - `--reload`가 `src/` 코드 변경을 watch → 코드 수정 시 자동 리로드.
  - 로그는 프로젝트 루트 `logs/server.log`.
- `send_docker_ps.sh [SERVER_NAME]` (primary+secondary, crontab 1분):
  - 서버 이름은 첫 인자로 전달(기본 `primary`), 그 외 설정은 `.env`에서 로드.
  - `X-API-Key` 헤더에 `DOCKERPORTINFO_PSK`를 실어 전송.
  - `docker ps` 실패/HTTP 비200 시 비정상 종료 코드로 로그 남김.

## 7. 인증 / 설정

- **사전 공유 키(PSK)**: `POST /docker/{server}/`는 `X-API-Key` 헤더가 `DOCKERPORTINFO_PSK`와
  일치해야 한다. 비교는 `hmac.compare_digest`로 상수 시간 비교한다. 불일치/누락 시 401.
- **설정 로딩(`src/config.py`)**: `.env`(실제, gitignore) → 없으면 `.env.default`(템플릿, 커밋) 순으로
  병합하고, 실제 환경변수가 최우선. PSK가 비어 있으면 인증을 끈다(개발 편의, 운영에선 항상 설정).
- 조회 API(`GET`)와 웹 페이지는 인증이 없다 — 연구실 내부망 + user 권한 전제.

## 8. 결정 사항 / 트레이드오프

- **원본 텍스트를 그대로 전송하고 서버에서 파싱**: 수집기를 단순(`docker ps` + `curl`)하게 유지하고,
  파싱 로직 변경 시 서버만 고치면 되도록 했다.
- **PSK는 헤더 1개로 단순 인증**: 내부망 전제라 mTLS/OAuth 대신 공유 키로 충분. 외부 노출 시
  리버스 프록시(TLS) 추가 권장.
- **단일 worker 가정**: `store`는 프로세스 내 dict. 다중 worker로 확장하려면 외부 저장소(redis 등) 필요.

## 9. 향후 확장 여지

- 서버/컨테이너 down 알림(임계 시간 초과 시 Slack 등).
- GPU 사용량(nvidia-smi) 수집 컬럼 추가.
- 스냅샷 이력 보관 및 변화 추적.
- 조회 API에도 인증/TLS 적용(외부 노출 시).
