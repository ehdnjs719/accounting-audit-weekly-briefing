# 설치 · 자동화 설정 가이드

전체 흐름: **① 로컬 테스트 → ② 네이버 메일 설정 → ③ GitHub 저장소 + Secrets → ④ Actions 수동 실행 확인 → ⑤ 로컬 폴더 동기화 등록**

---

## ① 로컬 테스트

```powershell
cd 문서\accounting-audit-weekly-briefing
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
.\.venv\Scripts\python.exe main.py --no-email --no-state
```

`문서\CPA_Weekly_Briefing\YYYY-MM-DD_주간회계·감사브리핑.pdf` 가 생기면 성공입니다.
(Windows 파일명에는 `/` 를 쓸 수 없어 `·` 로 바꿨습니다.)

## ② 네이버 메일(SMTP) 준비

1. 네이버 메일 → 왼쪽 아래 **환경설정** → **POP3/IMAP 설정** → **POP3/SMTP 사용: 사용함** → 저장
2. 네이버 2단계 인증을 쓰고 있다면: 네이버 내정보 → 보안설정 → **애플리케이션 비밀번호** 발급 → 이 값을 비밀번호로 사용
3. 로컬에서 메일까지 테스트하려면 `.env` 를 열어 채웁니다.

```
SMTP_USER=네이버아이디
SMTP_PASSWORD=비밀번호 또는 애플리케이션 비밀번호
MAIL_FROM=네이버아이디@naver.com
MAIL_TO=받을주소@naver.com
```

```powershell
.\.venv\Scripts\python.exe main.py --no-state
```

> `.env` 는 `.gitignore` 에 들어 있어 GitHub에 올라가지 않습니다.

## ③ GitHub 저장소 만들기 + Secrets 등록

1. GitHub에서 새 저장소 `accounting-audit-weekly-briefing` 생성 (**Public** 권장: 포트폴리오 공개 + 로컬 동기화가 토큰 없이 동작)
2. 이 폴더를 올립니다.

```powershell
git init
git add .
git commit -m "Initial commit: weekly accounting & audit briefing pipeline"
git branch -M main
git remote add origin https://github.com/ehdnjs719/accounting-audit-weekly-briefing.git
git push -u origin main
```

3. 저장소 → **Settings → Secrets and variables → Actions → New repository secret** 으로 아래를 등록

| Name | 값 |
|---|---|
| `SMTP_HOST` | `smtp.naver.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | 네이버 아이디 |
| `SMTP_PASSWORD` | 비밀번호 / 애플리케이션 비밀번호 |
| `MAIL_FROM` | `아이디@naver.com` |
| `MAIL_TO` | 받을 주소 (여러 명이면 쉼표로 구분) |
| `ANTHROPIC_API_KEY` | (선택) Claude API 키 — 없으면 규칙 기반 요약 |

4. 저장소 → **Settings → Actions → General → Workflow permissions → Read and write permissions** 선택 (PDF 커밋용)

## ④ 수동 실행으로 확인

저장소 → **Actions → Weekly Accounting & Audit Briefing → Run workflow**.
5~10분 뒤 메일이 오고 `reports/` 폴더에 PDF가 커밋되면 완료입니다.
이후에는 **매주 월요일 07:30 KST** 에 자동 실행됩니다. (GitHub 스케줄은 몇 분~20분 늦게 시작될 수 있어 30분 앞당겨 두었습니다.)

> ⚠️ GitHub는 **60일 동안 저장소 활동이 없으면 예약 워크플로를 자동 중지**합니다.
> 이 파이프라인은 매주 리포트를 커밋하므로 활동이 유지되지만, 중지 알림 메일이 오면 Actions 탭에서 다시 켜 주세요.

## ⑤ 로컬 폴더 자동 동기화 (작업 스케줄러)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Mode Sync -Repo "ehdnjs719/accounting-audit-weekly-briefing"
```

- 등록되는 작업: **CPA Weekly Briefing - Sync** (월 08:15 + 로그온할 때마다)
- 월요일 아침 노트북이 꺼져 있었다면, 켜고 로그인하는 순간 새 PDF가 `문서\CPA_Weekly_Briefing` 에 내려받아집니다.
- 기록: `logs\sync.log`

### GitHub 없이 PC에서만 돌리고 싶다면

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Mode Local
```

월 08:00 실행, 놓친 일정은 부팅 후 즉시 실행, 절전 상태면 깨워서 실행합니다. (완전히 꺼진 PC는 켤 수 없습니다.)

### 작업 삭제

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Unregister
```

## 자주 묻는 문제

| 증상 | 확인 |
|---|---|
| `SMTPAuthenticationError` | 네이버 POP3/SMTP 사용 설정, 2단계 인증 시 애플리케이션 비밀번호 |
| 부록에 "금융감독원 보도자료 → Google News 대체" | 해외 IP 접속 제한 등으로 사이트 수집 실패 → 언론 보도로 대체된 상태. 로컬 실행 시 정상 수집됨 |
| PDF 한글이 네모로 나옴 | 워크플로의 `fonts-noto-cjk` 설치 단계 확인 |
| 특정 법인이 계속 0건 | 사이트 개편 가능성 → `briefing/collectors/big4.py` 의 `FIRMS` URL·정규식 수정 |
