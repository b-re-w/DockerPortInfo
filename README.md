# DockerPortInfo

연구실 GPU 서버(**primary** / **secondary**)에서 Backend.ai가 띄운 Docker 컨테이너의
**이미지 정보**와 **포트 매핑**을 한 화면에서 모니터링하는 FastAPI 웹 서버입니다.

각 서버는 crontab으로 1분마다 `docker ps` 결과를 웹 서버로 전송하고, 웹 서버는 그 텍스트에서
필요한 내용만 추려 서버별 자료형으로 보관합니다. 웹 페이지는 렌더링 후 1분마다 자동으로 갱신됩니다.

예시:
- 이미지 `cr.backend.ai/multiarch/python:3.12-ubuntu24.04-cuda12.6.1`
  → **python 3.12 · ubuntu 24.04 · cuda 12.6** 으로 표기
- 포트 `168.188.127.233:30726->8180/tcp`
  → **컨테이너 8180 → 호스트 30726** 으로 표기

---

## 구조

```
DockerPortInfo/
├── src/                     # FastAPI 서버 코드
│   ├── app.py               # 엔드포인트 (수신 API + 조회 API + 페이지)
│   ├── parser.py            # docker ps 텍스트 → 자료형 파서
│   ├── models.py            # 서버별 보관 자료형 (Pydantic)
│   └── store.py             # 서버명 -> 최신 스냅샷 인메모리/디스크 저장소
├── res/                     # 웹 프론트엔드 정적 리소스
│   ├── index.html
│   ├── style.css
│   └── app.js               # 1분마다 /api/snapshots 폴링 → 화면 갱신
├── scripts/
│   ├── send_docker_ps.sh    # (primary+secondary) docker ps 결과 전송 — crontab
│   └── launch_server.sh     # (primary) 서버 기동/리로드 keepalive — crontab
├── logs/                    # 런타임 로그 (자동 생성, git 제외)
└── data/                    # 서버별 마지막 스냅샷 JSON (자동 생성, git 제외)
```

데이터 흐름:

```
[primary]   docker ps ─┐
                       ├─(POST BASE/<서버명>)─▶ [primary FastAPI:13000] ─▶ store ─▶ 웹 페이지(폴링)
[secondary] docker ps ─┘     (nginx https → 127.0.0.1:13000)
```

---

## API

모든 경로는 공통 prefix `DOCKERPORTINFO_BASE_PATH`(기본 `/info/docker`) 아래에 있습니다.
아래 `BASE`는 그 prefix를 의미합니다 (nginx `location` 과 동일하게 맞출 것).

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET`  | `BASE/` | 모니터링 웹 페이지 |
| `GET`  | `BASE/static/*` | 정적 자산(css/js) |
| `GET`  | `BASE/snapshots` | 모든 서버 스냅샷(JSON) — 프론트엔드 폴링 대상 |
| `GET`  | `BASE/{server_name}` | 해당 서버의 정리된 스냅샷(JSON) |
| `POST` | `BASE/{server_name}` | `docker ps` 원본 텍스트(text/plain) 수신·파싱·저장 — **`X-API-Key` 인증 필요** |
| `GET`  | `BASE/healthz` | 헬스 체크 |

> `{server_name}` 은 `snapshots`/`static`/`healthz` 와 같은 레벨이라, 이 이름들은 서버명으로 쓸 수 없습니다(primary/secondary 사용).
> prefix를 빈 값으로 두면 루트(`/`)에서 서비스됩니다.

### nginx (기존 HTTPS 서버에 붙이기)

기존 `dolab-gpu.duckdns.org` 의 443 블록에 [deploy/nginx.conf.example](deploy/nginx.conf.example) 의
`location /info/docker/` 블록을 추가하면 `https://dolab-gpu.duckdns.org/info/docker/` 로 노출됩니다.
`proxy_pass http://127.0.0.1:13000;` 에 **trailing slash/경로를 붙이지 않아** 원본 URI가 그대로 전달되는 것이 핵심입니다.

### 접속 IP에 따른 포트 비공개

`DOCKERPORTINFO_CAMPUS_CIDRS`(기본 `168.188.0.0/16`) 대역 **밖**에서 접속하면 페이지는 그대로 보이되,
각 컨테이너의 **포트 정보만 비공개** 처리되고 `"당신의 접속 IP는 …입니다. 학외 IP의 경우 포트 정보가 비공개됩니다."`
배너가 표시됩니다. 클라이언트 IP는 nginx가 넣는 `X-Real-IP`/`X-Forwarded-For`로 판별합니다.
(이미지 정보·서버 구성은 학외에서도 보입니다. 콤마로 여러 대역 지정 가능.)

---

## 빠른 설치 (setup.sh, 권장)

각 서버에서 한 줄로 의존성 설치·`.env` 구성·crontab 등록까지 끝냅니다. **멱등**이라 재실행해도 안전합니다.

```bash
chmod +x scripts/setup.sh

# primary (웹 서버 + 자기 전송). PSK 미지정 시 자동 생성되어 출력됩니다.
./scripts/setup.sh primary

# secondary (전송만). primary 가 출력한 PSK 사용. nginx https 경유 권장
./scripts/setup.sh secondary --psk <primary-PSK> --web-url https://dolab-gpu.duckdns.org
#   (내부 IP 직결 시: --web-url http://<primary-ip>:13000)
```

`setup.sh`가 하는 일:
- `.env` 생성/갱신 (PSK·WEB_URL·HOST·PORT). primary는 PSK 자동 생성 후 화면에 출력.
- primary 만 의존성 설치(`uv sync`, 없으면 `venv`+`pip`). secondary는 설치 불필요.
- `logs/`·`data/` 생성, 스크립트 실행권한 부여.
- crontab 1분 주기 등록(primary: 웹 keepalive + 전송 / secondary: 전송).
- primary는 서버 기동 + 초기 전송까지 시도.

> 옵션: `--port`, `--host`, `--no-cron`, `--no-start`. 자세한 건 `scripts/setup.sh` 상단 주석 참고.
> 아래 "설정(.env)/수동 등록"은 내부 동작을 이해하거나 수동으로 할 때 참고용입니다.

---

## 설정 (.env)

설정은 프로젝트 루트의 `.env` 파일에서 읽으며, 없는 값은 커밋된 템플릿 `.env.default`로 보완됩니다.
우선순위는 **실제 환경변수 > `.env` > `.env.default`** 입니다. `.env`는 `.gitignore`로 제외됩니다.

```bash
cp .env.default .env       # 최초 1회
# .env 를 열어 DOCKERPORTINFO_PSK 를 안전한 임의 값으로 교체
```

| 키 | 설명 |
| --- | --- |
| `DOCKERPORTINFO_PSK` | 수신 API 인증용 **사전 공유 키**. primary·secondary·웹 서버가 동일 값을 사용 |
| `DOCKERPORTINFO_SERVER_NAME` | (선택) 전송 시 서버 이름 기본값 |
| `DOCKERPORTINFO_WEB_URL` | (선택) 전송 대상 웹 서버 URL |
| `DOCKERPORTINFO_HOST` / `DOCKERPORTINFO_PORT` | (선택) 웹 서버 기동 호스트/포트 |

> **인증**: `POST /docker/{server}/` 는 `X-API-Key` 헤더의 값이 `DOCKERPORTINFO_PSK` 와 일치해야 하며,
> 불일치/누락 시 **401**을 반환합니다. (`send_docker_ps.sh`가 자동으로 헤더를 붙입니다.)
> 조회 API(`GET`)와 웹 페이지는 인증이 없습니다 — 내부망 사용 전제.

---

## 설치 & 실행 (primary 서버)

`docker ps`는 **sudo 없이** 실행 가능하다고 가정합니다.

```bash
# 의존성 설치 (uv 권장)
uv sync

# 수동 실행 (개발/확인용)
./scripts/launch_server.sh
# → http://<primary-ip>:13000/info/docker/ 접속 (nginx 뒤: https://dolab-gpu.duckdns.org/info/docker/)
```

`launch_server.sh`는 이미 떠 있으면 아무 것도 하지 않고, 죽어 있으면 다시 띄웁니다.
`uvicorn --reload`로 `src/` 코드 변경을 watch 하여 자동 리로드하며, 로그는 `logs/server.log`에 쌓입니다.

기본 호스트/포트는 환경변수로 조정합니다: `DOCKERPORTINFO_HOST`, `DOCKERPORTINFO_PORT`.

---

## crontab 등록

먼저 스크립트에 실행 권한을 줍니다.

```bash
chmod +x scripts/send_docker_ps.sh scripts/launch_server.sh
```

`crontab -e`로 편집합니다. 경로는 실제 설치 경로로 바꾸세요.

### primary 서버

서버 이름은 스크립트 첫 번째 인자로 넘깁니다(기본값 `primary`). PSK·웹 URL 등은 `.env`에서 읽힙니다.

```cron
# 웹 서버 keepalive (죽어 있으면 1분 내 재기동)
* * * * * /opt/DockerPortInfo/scripts/launch_server.sh >> /opt/DockerPortInfo/logs/launch.log 2>&1

# 자기 자신의 docker ps 를 로컬 웹 서버로 전송
* * * * * /opt/DockerPortInfo/scripts/send_docker_ps.sh primary >> /opt/DockerPortInfo/logs/sender.log 2>&1
```

### secondary 서버

웹 서버는 primary에만 두고, secondary는 전송만 합니다. secondary의 `.env`에는
**같은 `DOCKERPORTINFO_PSK`** 와 primary를 가리키는 `DOCKERPORTINFO_WEB_URL`을 설정합니다.

```bash
# secondary 의 .env 예시 — nginx https 경유 (권장: 포트 13000 노출 불필요)
DOCKERPORTINFO_PSK=<primary와 동일한 키>
DOCKERPORTINFO_WEB_URL=https://dolab-gpu.duckdns.org
# (BASE_PATH 는 기본 /info/docker → 최종 전송 대상: …/info/docker/secondary)

# 또는 내부 IP 직결 시: DOCKERPORTINFO_WEB_URL=http://<primary-ip>:13000
```

```cron
* * * * * /opt/DockerPortInfo/scripts/send_docker_ps.sh secondary >> /tmp/dpi-sender.log 2>&1
```

> https 도메인으로 보내면 nginx가 13000으로 프록시하므로 방화벽에 13000을 열 필요가 없습니다.
> 내부 IP 직결을 쓸 때만 primary의 13000 포트를 secondary에 개방하세요.

---

## 동작 확인

```bash
# 헬스 체크
curl http://127.0.0.1:13000/info/docker/healthz

# 전송 한 번 수동 실행 (.env 의 PSK·WEB_URL·BASE_PATH 사용, 서버 이름은 인자로)
./scripts/send_docker_ps.sh primary

# 키 없이 POST 하면 401 인지 확인
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:13000/info/docker/primary --data "x"

# 저장된 스냅샷 조회
curl http://127.0.0.1:13000/info/docker/primary
curl http://127.0.0.1:13000/info/docker/snapshots

# nginx 경유 (https)
curl https://dolab-gpu.duckdns.org/info/docker/snapshots
```

---

## 로그 관리 (회전)

로그는 프로젝트 루트의 `logs/`에 쌓입니다.

- `server.log` — uvicorn 출력(요청·에러). 가장 빠르게 증가.
- `sender.log` — 전송 스크립트가 매분 1줄.
- `launch.log` — 재기동 시에만 기록.

`setup.sh`가 [deploy/logrotate.example](deploy/logrotate.example)를 `/etc/logrotate.d/dockerportinfo`로
자동 설치합니다(`logrotate` + sudo 권한 필요). **매일 회전 + 7일 보관 후 자동 삭제**라 무한 누적되지 않습니다.

수동 설치/확인:

```bash
sed "s#__PROJECT_ROOT__#$(pwd)#g" deploy/logrotate.example | sudo tee /etc/logrotate.d/dockerportinfo
sudo logrotate --debug /etc/logrotate.d/dockerportinfo   # 설정 검증 (실제 회전 안 함)
sudo logrotate --force /etc/logrotate.d/dockerportinfo   # 즉시 한 번 회전 테스트
```

> `copytruncate`를 쓰므로 서버를 재시작하지 않고도 회전됩니다.

---

자세한 설계 배경은 [PROJECT.md](PROJECT.md) 참고.
