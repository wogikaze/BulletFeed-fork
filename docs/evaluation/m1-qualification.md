# M1 Zero-to-Useful-Feed qualification

M1には、service state transitionを直接検証する deterministic fixture と、FastAPIのHTTP契約を
fresh DBごとに検証する API qualification の二つを使う。

```text
cd backend
python scripts/run_m1_qualification.py --output tests/gold/m1_personas/v01/deterministic_baseline.json
python scripts/run_m1_api_qualification.py --output tests/gold/m1_personas/v01/api_qualification.json
```

API qualificationは30 constructed personaをそれぞれ別のfresh SQLite DBへ投入し、session/account、
profile、topic recommendation、onboarding、source discovery/activation、subscription、
worker subscription、worker acquisition、feed、Event evidence、exposure、feedback、read、
subsequent unread feed、tenant isolationを実FastAPI endpoint経由で検証する。worker acquisitionは
実際のWatchSyncWorkerのrefresh/lease/crawler/投影経路を通し、外部statuspage transportだけを
決定的なlocal acceptance summaryへ置き換える。外部OAuthやlive source fetchは使わない。

現在のAPI evidenceは30/30 persona、17 stage failure 0、worker acquisition failure 0、
unexpected empty 0、broken evidence 0、tenant leakage 0。active 28 personaはread後にcardが
unread feedから外れ、2 personaはno-topic abstentionを理由付きで通る。useful proxy@5/@10は
56/56、cards-to-first-usefulのactive中央値は1。

この結果はAPI/backend state transitionとworker orchestrationの証跡であり、workerによる実source
transport、Androidのphone/tablet UI、accessibility、release artifact、公開環境でのfield
validationを置き換えない。これらはM3/M4/M5/M7専用gateで別に測定する。
