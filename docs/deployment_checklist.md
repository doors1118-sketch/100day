# `/opt/minsaeng100` 배포 체크리스트

## 1. 실서버 사전 확인

```bash
df -h
free -h
ss -ltnp
systemctl --type=service --state=running
sudo nginx -T
crontab -l
sudo crontab -l
```

확인 기준:

- `/` 디스크 사용률 80% 미만 권장
- 메모리 여유 2GB 이상 권장
- `8010`, `8510` 포트 미사용
- 기존 `/opt/busan`, `/opt/advisor` git dirty 여부 확인
- 자동 배포 cron이 `/opt/advisor` 또는 공용 nginx 설정을 덮어쓰지 않는지 확인

## 2. 서버 폴더 생성

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin minsaeng
sudo mkdir -p /opt/minsaeng100
sudo chown -R minsaeng:minsaeng /opt/minsaeng100
```

## 3. 애플리케이션 설치

```bash
sudo -u minsaeng python3 -m venv /opt/minsaeng100/venv
sudo -u minsaeng /opt/minsaeng100/venv/bin/pip install -r /opt/minsaeng100/requirements.txt
sudo -u minsaeng /opt/minsaeng100/venv/bin/python /opt/minsaeng100/scripts/init_db.py
```

## 4. systemd 등록

```bash
sudo cp /opt/minsaeng100/deploy/systemd/minsaeng100-api.service /etc/systemd/system/
sudo cp /opt/minsaeng100/deploy/systemd/minsaeng100-dashboard.service /etc/systemd/system/
sudo cp /opt/minsaeng100/deploy/systemd/minsaeng100-collector.service /etc/systemd/system/
sudo cp /opt/minsaeng100/deploy/systemd/minsaeng100-collector.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now minsaeng100-api.service
sudo systemctl enable --now minsaeng100-dashboard.service
sudo systemctl enable --now minsaeng100-collector.timer
```

상태 확인:

```bash
systemctl status minsaeng100-api.service --no-pager
systemctl status minsaeng100-dashboard.service --no-pager
systemctl list-timers minsaeng100-collector.timer --no-pager
journalctl -u minsaeng100-collector.service -n 80 --no-pager
curl -fsS http://127.0.0.1:8010/health
```

## 5. nginx 반영

기존 server 블록에 `deploy/nginx/minsaeng100.conf`의 location을 병합한다.

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 6. 수동 입력 적재

```bash
/opt/minsaeng100/venv/bin/python /opt/minsaeng100/scripts/create_manual_xlsx_template.py
/opt/minsaeng100/venv/bin/python /opt/minsaeng100/scripts/import_manual_xlsx.py /opt/minsaeng100/data/manual/민생100일_정책금융_수동입력_서식.xlsx
```

CSV 파일로 나누어 적재해야 할 경우:

```bash
/opt/minsaeng100/venv/bin/python /opt/minsaeng100/scripts/import_manual_csv.py credit /opt/minsaeng100/data/manual/busan_credit_guarantee_monthly_template.csv
/opt/minsaeng100/venv/bin/python /opt/minsaeng100/scripts/import_manual_csv.py policy /opt/minsaeng100/data/manual/busan_policy_fund_monthly_template.csv
```

주의:

- 소상공인 특별자금은 전체 신용보증 공급규모의 세부 프로그램으로 표시한다.
- 전체 신용보증 공급규모와 특별자금을 합산하지 않는다.
- 사고율과 대위변제액은 이번 대시보드 범위에서 제외한다.
