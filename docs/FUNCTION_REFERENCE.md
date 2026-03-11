# Project Function Reference

Бұл құжат реподағы **жобаның өз коды** ішіндегі функцияларды/методтарды атайды және қысқаша түсіндіреді (тәуелділіктер `frontend/node_modules`, `__pycache__` т.б. есепке алынбады).

## Backend (FastAPI) — `backend/app`

### API entrypoints — `backend/app/main.py`

- `WsHub.__init__()` (`backend/app/main.py:31`) — WebSocket клиенттерін сақтау үшін жиын (`set`) және синхронизация үшін `asyncio.Lock()` дайындайды.
- `WsHub.add()` (`backend/app/main.py:35`) — жаңа WebSocket клиентті hub-қа қосады.
- `WsHub.remove()` (`backend/app/main.py:39`) — WebSocket клиентті hub-тан алып тастайды.
- `WsHub.broadcast_json()` (`backend/app/main.py:43`) — барлық қосылған клиенттерге JSON хабарламаны таратады (әр клиентке `_safe_send()` арқылы).
- `WsHub.count()` (`backend/app/main.py:53`) — қосылған WebSocket клиенттер санын қайтарады.
- `_safe_send()` (`backend/app/main.py:58`) — `ws.send_json(...)` қателерін “жұтып” жіберетін қауіпсіз жіберу.
- `_to_out()` (`backend/app/main.py:68`) — БД-дағы `TelemetryRow` → API-дің `TelemetryOut` форматына түрлендіреді: `score_risk()` және `extract_features()` нәтижелерін қосады.

FastAPI маршруттары:

- `health()` (`backend/app/main.py:95`) — `/api/health`: DB түрін/мақсатын, NASA baseline статустарын және WS клиенттер санын қайтарады.
- `ingest_telemetry()` (`backend/app/main.py:111`) — `/api/telemetry`: телеметрияны қабылдап БД-ға жазады, алдыңғы нүктемен салыстырып тәуекел/derived есептейді, WS арқылы broadcast жасайды.
- `latest()` (`backend/app/main.py:129`) — `/api/latest`: соңғы телеметрияны қайтарады (БД бос болса “empty” нүкте береді).
- `history()` (`backend/app/main.py:151`) — `/api/history`: соңғы N жазбаны уақыт ретімен қайтарады.
- `ws_endpoint()` (`backend/app/main.py:162`) — `/ws`: WebSocket қосылымын қабылдайды, қосылғанда latest жібереді, кейін keepalive қабылдап тұрады.
- `main()` (`backend/app/main.py:182`) — `uvicorn` арқылы backend серверін іске қосады (dev үшін `reload=True`).

### DB layer — `backend/app/db.py`

- `_sqlite_url_from_path()` (`backend/app/db.py:26`) — Windows-та SQLite URL үшін path-ты forward-slash форматына келтіреді.
- `Db.__init__()` (`backend/app/db.py:33`) — SQLAlchemy engine құрады, `telemetry` кестесін сипаттайды, schema-ны инициализациялайды (sqlite немесе env арқылы берілген URL).
- `Db.engine` (`backend/app/db.py:68`) — SQLAlchemy `Engine` қайтарады.
- `Db.url` (`backend/app/db.py:72`) — DB URL жолын қайтарады.
- `Db.safe_url()` (`backend/app/db.py:75`) — пароль болса жасырып көрсететін safe URL.
- `Db.kind()` (`backend/app/db.py:78`) — backend атауын қайтарады (`sqlite`, `postgresql`, ...).
- `Db.path` (`backend/app/db.py:82`) — sqlite файл path-ы (егер `db_url` қолданылса `None`).
- `Db._init_schema()` (`backend/app/db.py:85`) — кестелерді `create_all` арқылы жасайды.
- `Db.insert()` (`backend/app/db.py:89`) — телеметрияны кестеге жазады да `TelemetryRow` қайтарады (Postgres-та `RETURNING`, sqlite-та `lastrowid`/`max(id)` fallback).
- `Db._row_to_model()` (`backend/app/db.py:132`) — SQLAlchemy mapping row → `TelemetryRow`.
- `Db.latest()` (`backend/app/db.py:144`) — ең соңғы жазбаны қайтарады.
- `Db.previous()` (`backend/app/db.py:153`) — берілген `before_id`-ден бұрынғы соңғы жазбаны қайтарады.
- `Db.history()` (`backend/app/db.py:167`) — соңғы `limit` жазбаны алып, уақыт ретімен қайтарады (іште `limit` 1..10000 clamp).

### Feature engineering — `backend/app/features.py`

- `extract_features()` (`backend/app/features.py:16`) — `pulse_rate` (pulses/sec) сияқты derived feature-лерді есептейді; `previous` болса `dt` бойынша нормализациялайды.

### API схемалары — `backend/app/models.py`

- `utc_now()` (`backend/app/models.py:9`) — UTC уақыттағы `datetime.now(timezone.utc)` қайтарады.

### Settings — `backend/app/settings.py`

- `load_settings()` (`backend/app/settings.py:17`) — `.env` оқиды (`dotenv`), `DT_DB_URL/DT_DB_PATH/DT_CORS_ALLOW_ORIGINS` арқылы `Settings` құрайды.

### NASA baseline — `backend/app/nasa_baseline.py`

- `baseline_path()` (`backend/app/nasa_baseline.py:21`) — baseline JSON path (әдепкі `backend/app/ml/nasa_baseline.json`, env: `DT_NASA_BASELINE_PATH`).
- `get_baseline()` (`backend/app/nasa_baseline.py:29`) — baseline JSON-ды оқиды, `mtime` бойынша кэш жасайды, feature mean/std-ты `FeatureStats`-қа айналдырады.
- `baseline_file_exists()` (`backend/app/nasa_baseline.py:69`) — baseline файлы бар-жоғын тексереді.
- `baseline_active()` (`backend/app/nasa_baseline.py:73`) — baseline оқылып тұрғанын (`get_baseline()!=None`) айтады.

### NASA RUL model — `backend/app/nasa_rul.py`

- `model_path()` (`backend/app/nasa_rul.py:27`) — RUL model JSON path (әдепкі `backend/app/ml/nasa_rul_model.json`, env: `DT_NASA_RUL_MODEL_PATH`).
- `get_rul_model()` (`backend/app/nasa_rul.py:37`) — model JSON-ды оқиды, `mtime` бойынша кэш жасайды, `points`-ты сорттайды.
- `model_file_exists()` (`backend/app/nasa_rul.py:89`) — model файлы бар-жоғын тексереді.
- `model_active()` (`backend/app/nasa_rul.py:93`) — model оқылып тұрғанын (`get_rul_model()!=None`) айтады.
- `estimate_rul_seconds()` (`backend/app/nasa_rul.py:97`) — ағымдағы `vibration` мәнін model-дің “envelope” қисығына сәйкестендіріп, `t_end - t_at` арқылы қалған ресурсты (секунд) бағалайды.

### Risk scoring — `backend/app/risk.py`

- `_env_float()` (`backend/app/risk.py:13`) — env-тан float оқиды, қате/бос болса default қайтарады.
- `_clamp01()` (`backend/app/risk.py:60`) — мәнді 0..1 диапазонына қысқыштайды.
- `_dedup()` (`backend/app/risk.py:63`) — тізімдегі қайталанатын жолдарды алып тастайды (ретін сақтайды).
- `score_risk()` (`backend/app/risk.py:72`) — негізгі тәуекелді есептейді:
  - температура/ток/вибрация шектері және алдыңғы нүктемен салыстырғандағы тренд (rate) арқылы базалық score;
  - егер NASA baseline бар болса — z-score аномалиясымен score-ды күшейтеді (flicker азайту үшін streak confirm қолданады);
  - егер NASA RUL model бар болса — RUL бағасын ETA ретінде береді және қажет болса score-ға әсер етеді;
  - `is_running=false` кезінде “нейтрал” күйге түсіреді.
- `z()` (`backend/app/risk.py:190`) — **локалды helper** ( `score_risk()` ішінде): baseline mean/std арқылы feature z-score есептейді (вибрацияға “тек жоғарылағаны маңызды” логикасы бар).

## ML utilities — `backend/app/ml`

### Baseline builder — `backend/app/ml/build_baseline_from_csv.py`

- `Stats.add()` (`backend/app/ml/build_baseline_from_csv.py:17`) — бір өтуде mean/std есептеу үшін (Welford) статистика жинайды.
- `Stats.std()` (`backend/app/ml/build_baseline_from_csv.py:24`) — жинақталған `m2` арқылы стандартты ауытқуды қайтарады.
- `main()` (`backend/app/ml/build_baseline_from_csv.py:30`) — CSV оқып, бағандар бойынша mean/std есептеп, `nasa_baseline.json` жазады.

### RUL model builder — `backend/app/ml/build_rul_model_from_csv.py`

- `_parse_ims_timestamp()` (`backend/app/ml/build_rul_model_from_csv.py:16`) — файл атынан/жолынан IMS timestamp-ты тауып `datetime`-қа парс етеді.
- `_median()` (`backend/app/ml/build_rul_model_from_csv.py:31`) — тізім медианасын есептейді.
- `_ema()` (`backend/app/ml/build_rul_model_from_csv.py:42`) — EMA smoothing (экспоненциалды орташа) жасайды.
- `_envelope()` (`backend/app/ml/build_rul_model_from_csv.py:54`) — уақыт бойынша монотонды “max so far” envelope құрады.
- `main()` (`backend/app/ml/build_rul_model_from_csv.py:63`) — IMS features CSV-дан `nasa_rul_model.json` құрады (уақыт осін timestamp-тан немесе fallback индекс арқылы).

### IMS features extractor — `backend/app/ml/ims_to_features_csv.py`

- `_is_number()` (`backend/app/ml/ims_to_features_csv.py:10`) — жолды float-қа айналдыруға бола ма, тексереді.
- `_read_signal()` (`backend/app/ml/ims_to_features_csv.py:18`) — IMS txt файлынан амплитуда тізімін оқиды (қатеге төзімді: соңғы numeric token-ды алады).
- `_kurtosis()` (`backend/app/ml/ims_to_features_csv.py:42`) — kurtosis (4-ші момент) есептейді.
- `extract_features()` (`backend/app/ml/ims_to_features_csv.py:54`) — `rms/peak/kurtosis` шығарады.
- `main()` (`backend/app/ml/ims_to_features_csv.py:64`) — папкадағы файлдарды рекурсив қарап, features CSV жазады (таңдалған feature-ді `vibration` бағанына маптайды).

## Gateway (Arduino → Backend) — `gateway/gateway.py`

- `utc_now_iso()` (`gateway/gateway.py:17`) — UTC ISO timestamp қайтарады.
- `Telemetry.to_api_payload()` (`gateway/gateway.py:30`) — backend `/api/telemetry` үшін JSON payload құрады (`ts` ішіне `utc_now_iso()` қояды).
- `parse_line()` (`gateway/gateway.py:42`) — serial-дан келген бір жолды `Telemetry`-ге айналдырады (JSON line немесе CSV fallback).
- `post_telemetry()` (`gateway/gateway.py:74`) — backend-ке POST жасайды; 4xx болса payload+detail қоса error лақтырады.
- `simulate_stream()` (`gateway/gateway.py:92`) — Arduino жоқ кезде синтетикалық телеметрия генерациялайтын генератор (`yield Telemetry`).
- `run_simulate()` (`gateway/gateway.py:122`) — `simulate_stream()` → `post_telemetry()` циклымен дерек жіберіп тұрады.
- `run_serial()` (`gateway/gateway.py:133`) — COM порттан оқиды (`pyserial`), әр жолды парс етіп backend-ке жібереді; қателерде reconnect жасайды.
- `main()` (`gateway/gateway.py:182`) — CLI аргументтерін оқиды да simulate немесе serial режимін іске қосады.

## Frontend (Next.js/React) — `frontend`

### App shell — `frontend/app`

- `RootLayout()` (`frontend/app/layout.tsx:8`) — Next.js layout: HTML skeleton және глобал CSS қосады.
- `Page()` (`frontend/app/page.tsx:3`) — басты бет: header және `Dashboard` компонентін шығарады.

### Dashboard UI — `frontend/components/Dashboard.tsx`

- `levelColor()` (`frontend/components/Dashboard.tsx:53`) — risk level → CSS color token.
- `fmt()` (`frontend/components/Dashboard.tsx:59`) — санды `toFixed` форматқа келтіреді (NaN/Inf болса `-`).
- `fmtDuration()` (`frontend/components/Dashboard.tsx:64`) — секундты `s/min/h` форматқа түрлендіреді.
- `shortTime()` (`frontend/components/Dashboard.tsx:73`) — ISO timestamp-ты UI үшін қысқа уақытқа форматтайды.
- `Dashboard()` (`frontend/components/Dashboard.tsx:78`) — негізгі UI:
  - `useMemo` арқылы chart data дайындайды;
  - `useEffect` ішінде `boot()` (`frontend/components/Dashboard.tsx:99`) — `/api/latest`, `/api/history`, `/api/health` fetch жасап initial state толтырады;
  - екінші `useEffect` — WebSocket (`/ws`) қосып, келген телеметриямен state/history жаңартады, ping keepalive жібереді.

Ескерту: `Dashboard()` ішінде `useEffect/useMemo` callback-тері және WS event handler-лері сияқты **аноним** функциялар да бар, бірақ олар жеке экспортталмайды — компонент логикасының бөлігі ретінде жұмыс істейді.

## Arduino — `arduino`

### Негізгі скетч — `arduino/motor_tester_final.ino`

- `countPulse()` (`arduino/motor_tester_final.ino:42`) — interrupt handler: импульс санағышты арттырады.
- `setup()` (`arduino/motor_tester_final.ino:60`) — pin/interrupt, LCD, Serial, ACS712 zero calibration, MPU6050, DS18B20, SD init жасайды.
- `loop()` (`arduino/motor_tester_final.ino:117`) — негізгі цикл: encoder батырмасымен start/stop, running кезінде сенсор оқу/телеметрия шығару, idle кезінде тек PWM реттеу.
- `updateVibrationRms()` (`arduino/motor_tester_final.ino:202`) — MPU6050 аксель бойынша high-pass + 1 секундтық RMS window арқылы `vibrationRms` есептейді.
- `scanSensors()` (`arduino/motor_tester_final.ino:247`) — токты (A0) бірнеше өлшемнің орташа мәнімен есептейді, max жаңартады.
- `updateResearchDisplay()` (`arduino/motor_tester_final.ino:256`) — LCD-ға temp/amps/pulses/max vib шығарады.
- `showIdleScreen()` (`arduino/motor_tester_final.ino:267`) — idle экранын көрсетеді.
- `handleEncoder()` (`arduino/motor_tester_final.ino:276`) — rotary encoder арқылы PWM (`motorSpeed`) өзгерту, running болса PWM apply және бірден телеметрия шығару.
- `saveDataToSD()` (`arduino/motor_tester_final.ino:305`) — SD картаға тест нәтижелерін (`motor.txt`) append етеді.
- `printTelemetryJson()` (`arduino/motor_tester_final.ino:328`) — Serial-ға бір жолдық JSON телеметрия шығарады (gateway `parse_line()` соны оқиды).
- `updateTempNonBlocking()` (`arduino/motor_tester_final.ino:345`) — DS18B20-ды блоктамай оқу: conversion request → ~110ms кейін мәнін алу.

### Қысқа мысал — `arduino/serial_telemetry_snippet.ino`

- `printTelemetryJson()` (`arduino/serial_telemetry_snippet.ino:4`) — минималды snippet: Serial-ға JSON телеметрияны бір жол қылып шығару.

