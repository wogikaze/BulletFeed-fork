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
acceptance acquisition、feed、Event evidence、exposure、feedback、read、subsequent unread feed、
tenant isolationを実FastAPI endpoint経由で検証する。外部OAuthやlive source fetchは使わず、source
acquisitionはlocal acceptance seed fixtureとする。

現在のAPI evidenceは30/30 persona、16 stage failure 0、unexpected empty 0、broken evidence 0、
tenant leakage 0。active 28 personaはread後にcardがunread feedから外れ、2 personaはno-topic
abstentionを理由付きで通る。useful proxy@5/@10は56/56、cards-to-first-usefulのactive中央値は1。

この結果はAPI/backend state transitionの証跡であり、workerの実source acquisition、Androidの
phone/tablet UI、accessibility、release artifact、公開環境でのfield validationを置き換えない。
これらはM4/M5/M7専用gateで別に測定する。
