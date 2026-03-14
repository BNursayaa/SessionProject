# ML / NASA comparison (MVP explanation)

Бұл папкада 2 бөлік бар:

1) **Offline (дайындау құралдары)** — датасеттен feature шығару және baseline/RUL файлдарын генерациялау.
2) **Runtime (backend қолданатын файлдар)** — backend іске қосылғанда оқылатын дайын JSON-дар.

## Runtime файлдар (backend нақты қолданады)

- `backend/app/ml/nasa_baseline.json`
  - Ішінде baseline статистика болады: әр feature үшін `mean` және `std`.
  - Backend оны `z-score` арқылы “аномалия” табу үшін қолданады.
- `backend/app/ml/nasa_rul_model.json` (optional)
  - IMS “run-to-failure” вибрация envelope қисығы.
  - Backend осы қисыққа “теңестіріп” ETA (RUL) бағалайды.

## Offline файлдар (генерация үшін ғана)

- `backend/app/ml/ims_to_features_csv.py`
  - NASA IMS Bearings raw txt файлдарынан feature шығарады: `rms`, `peak`, `kurtosis`.
  - Нәтижесі: `ims_features.csv`.
- `backend/app/ml/build_baseline_from_csv.py`
  - CSV-дан `mean/std` есептеп `nasa_baseline.json` жасайды.
- `backend/app/ml/build_rul_model_from_csv.py`
  - `ims_features.csv` бойынша envelope curve жасап `nasa_rul_model.json` жасайды.
- `backend/app/ml/ims_features.csv`
  - Бұл тек аралық artifact (генерация нәтижесі). Runtime үшін міндетті емес.
  - Қаласаңыз git-қа қоспай, кез келген уақытта қайта генерациялай аласыз.

## “Бұл алгоритм бе, әлде формула ма?”

Комиссияға түсіндіру үшін дұрыс атауы:

- **Алгоритм (әдіс):** anomaly detection / статистикалық салыстыру
- **Модель:** baseline статистикасы (`mean/std`)
- **Есептеу:** z-score

Z-score формула:

`z = (x - mean) / std`

Бізде вибрация үшін бір нюанс бар: “төмен вибрация” көбіне проблема емес (төмен PWM/жүктеме),
сондықтан тек жоғары жағын қараймыз:

`z_vib = max(0, (x - mean) / std)`

Сосын:

- WARNING: `z >= DT_NASA_BASELINE_WARN_Z` бірнеше рет қатарынан (confirm samples)
- CRITICAL: `z >= DT_NASA_BASELINE_CRIT_Z` бірнеше рет қатарынан

Бұл “trained ML” (нейронка/RandomForest) емес, бірақ **өндірісте жиі қолданылатын** қарапайым әрі қорғалатын MVP тәсіл.

## Неге `nasa_baseline.json`-да тек vibration mean/std ғана?

Себебі NASA IMS Bearings датасеті сіздің Arduino телеметрияңыздағы `temp_c/amps` сияқты сигналдарды бермейді.
Ортақ ең ұқсас сигнал — вибрация.

Сол үшін біз NASA baseline-ды әзірге тек вибрациямен жасаймыз:

- логикасы дұрыс: “менің мотор вибрациям NASA-дегі ‘normal’ baseline-тан қаншалықты ауытқыды?”
- бірақ міндетті түрде **калибровка керек**.

## Калибровка (өте маңызды)

NASA IMS вибрациясы (RMS) және сіздің MPU6050 “vibration” мәні бір шкалада емес.
Сондықтан backend-та scale қолданылады:

- `DT_NASA_VIBRATION_SCALE`

Backend NASA-мен салыстыру үшін мынадай түрлендіру жасайды:

`vibration_nasa_domain = vibration_raw * DT_NASA_VIBRATION_SCALE`

Және `/api/health` ішінде `nasa_vibration.warn_raw/crit_raw` көрсетіледі — бұл сіздің raw вибрацияңызда
қандай мәнде WARNING/CRITICAL шығатынын түсіндіреді.

## Predictive maintenance “вибрация бойынша” ма?

Иә:

1) **Rule-based** шектер (temp/amps/vibration) — сіздің мотордың өз шкаласында.
2) **NASA baseline** (z-score) — вибрацияны NASA доменіне scale етіп салыстыру.
3) **NASA RUL (optional)** — вибрация envelope бойынша ETA.

Келесі деңгейге шығару үшін (толық ML):
- өз моторыңыздан көп дерек жинау
- fault label (подшипник тозуы, дисбаланс, т.б.) қою
- feature engineering (RMS/peak/kurtosis/FFT)
- supervised модель (мысалы XGBoost/RandomForest) үйрету

